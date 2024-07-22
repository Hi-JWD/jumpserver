import base64
import os
import json

import paramiko

from django.utils.translation import gettext as _
from django.conf import settings
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import models
from django.forms.models import model_to_dict
from paramiko.ssh_exception import SSHException

from accounts.models import Account
from assets.models import Protocol, Database, Platform, Asset
from assets.const import Protocol as const_p, WORKER_NAME
from behemoth.backends import cmd_storage
from behemoth.const import (
    TaskStatus, CommandStatus, PlanStrategy, PlanCategory,
    CommandCategory, WorkerPlatform, PlaybackStrategy, ExecutionCategory
)
from behemoth.utils import encrypt_json_file, colored_printer as p
from common.db.encoder import ModelJSONFieldEncoder
from common.utils import get_logger
from common.utils.timezone import local_now_date_display
from common.exceptions import JMSException
from jumpserver.settings import get_file_md5
from jumpserver.utils import get_current_request
from orgs.mixins.models import JMSOrgBaseModel
from orgs.mixins.models import OrgManager


logger = get_logger(__name__)


class WorkerQuerySet(OrgManager):
    def get_queryset(self):
        return super().get_queryset().filter(platform__name=WORKER_NAME)

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False):
        for obj in objs:
            obj.platform = Worker.default_platform()
        return super().bulk_create(objs, batch_size, ignore_conflicts)


class Worker(Asset):
    accounts: models.QuerySet
    protocols: models.QuerySet

    base = models.CharField(
        max_length=16, choices=WorkerPlatform.choices, default=WorkerPlatform.linux, verbose_name=_('Platform')
    )
    meta = models.JSONField(encoder=ModelJSONFieldEncoder, default=dict, verbose_name=_('Meta'))
    objects = WorkerQuerySet()

    class Meta:
        verbose_name = _('Worker')

    def __str__(self):
        return self.name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ssh_client: paramiko.SSHClient | None = None
        self._local_script_file: str = os.path.join(
            settings.APPS_DIR, 'libs', 'exec_scripts', 'worker'
        )
        self._remote_script_path = ''

    @property
    def envs(self):
        return self.meta.get('envs', '')  # noqa

    def __get_ssh_client(self):
        try:
            account: Account = self.get_account()
        except Exception as error:
            logger.error(f'Task worker get account failed: {error}')
            return None

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.address, port=self.get_target_ssh_port(),
            username=account.username, password=account.password, timeout=15
        )
        return client

    @property
    def ssh_client(self):
        if self._ssh_client is None:
            self._ssh_client = self.__get_ssh_client()
        return self._ssh_client

    def save(self, *args, **kwargs):
        self.platform = self.default_platform()
        return super().save(*args, **kwargs)

    @classmethod
    def default_platform(cls):
        return Platform.objects.get(name=WORKER_NAME, internal=True)  # noqa

    def get_account(self) -> Account:
        # 后续的账号选择策略从这里搞
        account: Account = self.accounts.first()
        if account is None:
            raise ValidationError({
                'worker': _('%s has no account' % self)
            })
        return account

    def get_port(self, protocol=const_p.ssh) -> int:
        try:
            protocol: Protocol = self.protocols.get(name=protocol)
            port = protocol.port
        except ObjectDoesNotExist:
            port = 0
        return port

    def test_connectivity(self) -> bool:
        connectivity: bool = False
        try:
            client = self.__get_ssh_client()
            if connectivity := bool(client):
                client.close()
        except Exception as error:
            logger.error(f'Task worker test ssh connect failed: {error}')
        return connectivity

    def _scp(self, local_path: str, remote_path: str, mode=0o544) -> None:
        sftp = self.ssh_client.open_sftp()
        try:
            sftp.remove(remote_path)
        except IOError:
            pass
        sftp.put(local_path, remote_path)
        sftp.chmod(remote_path, mode)
        sftp.close()

    def __ensure_script_exist(self) -> None:
        print(p.info('正在处理脚本文件'))
        platform_named = {
            'mac': ('jms_cli_darwin', '/tmp/behemoth', 'md5'),
            'linux': ('jms_cli_linux', '/tmp/behemoth', 'md5sum'),
            'windows': ('jms_cli_windows.exe', r'C:\Windows\Temp', ''),
        }
        filename, remote_dir, md5_cmd = platform_named.get(str(self.base), ('', '', ''))
        if not filename:
            raise JMSException(_('The worker[%s](%s) type error') % (self, self.type))

        self._remote_script_path = os.path.join(remote_dir, filename)
        local_path = os.path.join(
            settings.APPS_DIR, 'behemoth', 'libs', 'go_script', filename
        )
        command = f'{md5_cmd} {self._remote_script_path}'
        __, stdout, __ = self.ssh_client.exec_command(command)
        stdout = stdout.read().decode().split()
        local_exist = os.path.exists(local_path)
        if not local_exist:
            raise JMSException(_('Worker script(%s) does not exist') % filename)

        if local_exist and len(stdout) > 0 and get_file_md5(local_path) == stdout[0].strip():
            return

        self.ssh_client.exec_command(f'mkdir -p {os.path.dirname(self._remote_script_path)}')
        self._scp(local_path, self._remote_script_path)

    def __process_commands_file(
            self, remote_commands_file: str, local_commands_file: str, token: str, **kwargs: dict
    ) -> None:
        print(p.info('正在生成命令文件'))
        encrypted_data = kwargs.get('encrypted_data', False)
        if encrypted_data:
            local_commands_file = encrypt_json_file(local_commands_file, token[:32])

        self.ssh_client.exec_command(f'mkdir -p {os.path.dirname(remote_commands_file)}')
        self._scp(local_commands_file, remote_commands_file, mode=0o400)
        print(p.green('命令文件传输成功'))

    def __process_file(self, **kwargs: dict) -> None:
        self.__ensure_script_exist()
        self.__process_commands_file(**kwargs)

    def __clear(self, remote_commands_file: str, local_commands_file: str, **kwargs: dict) -> None:
        # 清理远端文件
        command = f'rm -f {remote_commands_file}'
        __, stdout, __ = self.ssh_client.exec_command(command)
        if stdout.channel.recv_exit_status() == 0:  # TODO 这里要改一下，状态码判断有问题
            logger.warning(f'Remote file({remote_commands_file}) deletion failed')
        # 清理本地文件
        os.remove(local_commands_file)

    def __execute_cmd(self, **kwargs: dict) -> None:
        print(p.info('开始执行命令\n'))
        revert_key = {'remote_commands_file': 'cmd_filepath'}
        params = {revert_key.get(k, k): v for k, v in kwargs.items()}
        encoded_data = base64.b64encode(json.dumps(params).encode()).decode()
        try:
            cmd = f'{self._remote_script_path} --command {encoded_data} --with_env'
            logger.debug('Behemoth cmd: %s' % cmd)
            __, stdout, stderr = self.ssh_client.exec_command(cmd)
            error = stderr.read().decode()
            if error:
                raise JMSException(error)
        except SSHException as e:
            raise JMSException(str(e))

    def __execute(self, **kwargs: dict) -> None:
        self.__process_file(**kwargs)
        self.__execute_cmd(**kwargs)

    def run(self, run_params: dict) -> None:
        self.__execute(**run_params)
        # self.__clear(**run_params) # TODO 后续放开


class Command(JMSOrgBaseModel):
    """
    任务类型为“同步”，后续考虑保存并创建execution会多复制一份冗余的command对象集，用来保存对应的命令执行结果
    怎么根据“部署”去分类这些命令需要考虑一下
    """
    input = models.TextField(blank=True, verbose_name=_('Input'))
    output = models.CharField(max_length=1024, blank=True, verbose_name=_('Output'))
    index = models.IntegerField(db_index=True, verbose_name=_('Index'))
    status = models.CharField(max_length=32, default=CommandStatus.not_start, verbose_name=_('Status'))
    execution_id = models.CharField(max_length=36, verbose_name=_('Execution'))
    timestamp = models.IntegerField(default=0, db_index=True)
    category = models.CharField(max_length=16, default=CommandCategory.command, verbose_name=_('Category'))
    pause = models.BooleanField(default=False, verbose_name=_('Pause'))
    relation_id = models.CharField(default=None, null=True, max_length=36, verbose_name=_('Sync plan relation'))

    class Meta:
        verbose_name = _('Command')
        ordering = ('index',)

    def __str__(self):
        return '%s(%s)' % (self.category, self.input[:10])

    def to_dict(self):
        fields = ['input', 'category', 'pause']
        if self.category == CommandCategory.pause:
            fields += ['output']
        return model_to_dict(self, fields=fields)


class Environment(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    assets = models.ManyToManyField('assets.Database', verbose_name=_("Assets"))


class Playback(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name='playbacks',
        null=True, verbose_name=_('Environment')
    )

    @staticmethod
    def _create_command(**data):
        Command.objects.create()

    def create_pause(self, pause_data):
        # TODO 这里插入的暂停要给所有这个回放关联的同步计划添加到最后执行的execution的最后一条命令上
        execution = Execution.objects.create(name=_('Pause'))
        Command.objects.create(
            input=pause_data['input'], output=pause_data['output'], index=0,
            execution_id=execution.id, category=CommandCategory.pause,
            pause=pause_data['pause'], status=CommandStatus.success,
        )

        pe = PlaybackExecution.objects.create(
            playback=self, execution=execution, plan_name=pause_data['input']
        )
        plan_objs = self.plans.filter(category=PlanCategory.sync) # noqa
        for plan in plan_objs:
            obj = SyncPlanCommandRelation.objects.create(
                plan_name=pe.plan_name, sync_plan=plan
            )
            if plan_e := plan.executions.first():
                plan_e.cmd_idx += 1
                Command.objects.create(
                    input=pause_data['input'], output=pause_data['output'],
                    index=plan_e.cmd_idx, execution_id=plan_e.id, relation_id=obj.id,
                    category=CommandCategory.pause, pause=pause_data['pause'],
                )
                meta_obj = plan_e.get_meta_obj()
                meta_obj.meta.update({meta_obj.get_next_serial(): {'cmd_range': 1}})
                meta_obj.save(update_fields=['meta'])
                plan_e.save(update_fields=['cmd_idx'])


class Plan(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    plan_strategy = models.CharField(
        max_length=32, default=PlanStrategy.failed_stop,
        choices=PlanStrategy.choices, verbose_name=_('Plan strategy')
    )
    playback_strategy = models.CharField(
        max_length=32, default=PlaybackStrategy.auto,
        choices=PlaybackStrategy.choices, verbose_name=_('Playback strategy')
    )
    category = models.CharField(
        max_length=32, default=PlanCategory.deploy,
        choices=PlanCategory.choices, verbose_name=_('Category')
    )
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name='instructions', verbose_name=_('Environment')
    )
    asset = models.ForeignKey(Database, null=True, on_delete=models.SET_NULL, verbose_name=_('Asset'))
    account = models.ForeignKey(Account, null=True, on_delete=models.SET_NULL, verbose_name=_('Account'))
    playback = models.ForeignKey(
        Playback, related_name='plans', null=True, on_delete=models.SET_NULL, verbose_name=_('Playback')
    )
    status = models.CharField(max_length=32, default=TaskStatus.not_start, verbose_name=_('Status'))

    class Meta:
        verbose_name = _('Plan')
        ordering = ('-date_created',)

    def create_execution(self):
        request = get_current_request()
        return Execution.objects.create(plan=self, user_id=request.user.id)


class PlanExecution(JMSOrgBaseModel):
    execution_id = models.UUIDField(verbose_name=_('Execution'))
    meta = models.JSONField(default=dict, verbose_name=_('Plan meta'))

    def get_next_serial(self):
        return len(self.meta.keys()) # noqa


class Execution(JMSOrgBaseModel):
    name = models.CharField(default='', max_length=128, verbose_name=_('Name'))
    plan = models.ForeignKey(
        Plan, null=True, on_delete=models.CASCADE, related_name='executions', verbose_name=_('Plan')
    )
    category = models.CharField(
        max_length=32, default=ExecutionCategory.cmd,
        choices=ExecutionCategory.choices, verbose_name=_('Category')
    )
    worker = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, related_name='e1s', verbose_name=_('Worker')
    )
    asset = models.ForeignKey(
        Database, on_delete=models.CASCADE, null=True, related_name='e2s', verbose_name=_('Asset')
    )
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, verbose_name=_('Account'))
    user_id = models.CharField(max_length=36, verbose_name=_('User'))
    reason = models.CharField(max_length=512, default='-', verbose_name=_('Reason'))
    status = models.CharField(max_length=32, default=TaskStatus.not_start, verbose_name=_('Status'))
    task_id = models.CharField(max_length=36, default='', verbose_name=_('Task ID'))
    cmd_idx = models.IntegerField(default=-1, verbose_name=_('Current command index'))

    class Meta:
        verbose_name = _('Task')
        ordering = ('date_created',)

    def get_meta_obj(self):
        return PlanExecution.objects.get_or_create(execution_id=self.id)[0]

    def generate_name(self):
        return f'{self.plan.name}-{local_now_date_display()}'[:128]

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = self.generate_name()
        return super().save(*args, **kwargs)

    def get_commands(self, get_all=True):
        queryset = cmd_storage.get_queryset().filter(execution_id=self.id)
        if not get_all:
            queryset = queryset.exclude(status=CommandStatus.success)
        return queryset
    
    
class SyncPlanCommandRelation(JMSOrgBaseModel):
    plan_name = models.CharField(max_length=128, verbose_name=_('Plan name'))
    sync_plan = models.ForeignKey(
        Plan, related_name='relations', on_delete=models.CASCADE, verbose_name=_('Sync plan')
    )


class PlaybackExecution(JMSOrgBaseModel):
    playback = models.ForeignKey(
        Playback, related_name='executions', on_delete=models.CASCADE, verbose_name=_('Playback')
    )
    execution = models.ForeignKey(Execution, on_delete=models.CASCADE, verbose_name=_('Execution'))
    plan_name = models.CharField(max_length=128, verbose_name=_('Plan name'))
    meta = models.JSONField(default=dict, verbose_name=_('Meta'))

    class Meta:
        ordering = ('date_created',)


class Instruction(JMSOrgBaseModel):
    content = models.TextField(null=True, blank=True, verbose_name=_('Content'))
    index = models.IntegerField(db_index=True, verbose_name=_('Index'))
    plan = models.ForeignKey(
        Plan, on_delete=models.CASCADE, related_name='instructions', null=True, verbose_name=_('Plan')
    )

    class Meta:
        verbose_name = _('Instruction')
        ordering = ('-date_created', 'index')


class Iteration(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))

    class Meta:
        verbose_name = _('Iteration')
