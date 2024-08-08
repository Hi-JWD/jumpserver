import base64
import os
import json
import uuid

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
    WorkerPlatform, PlaybackStrategy, ExecutionCategory
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
        filename = os.path.basename(remote_path)
        print(p.info(f'【%s】 %s: %s' % (_('Start'), _("Upload file"), filename)))
        sftp = self.ssh_client.open_sftp()
        try:
            sftp.remove(remote_path)
        except IOError:
            pass
        sftp.put(local_path, remote_path)
        sftp.chmod(remote_path, mode)
        sftp.close()
        print(p.info(f'【%s】 %s: %s' % (_('End'), _("Upload file"), filename)))

    def __ensure_script_exist(self) -> None:
        print(p.info(f'【%s】%s' % (_('Start'), _("Processing script file"))))
        platform_named = {
            'mac': ('jms_cli_darwin', '/tmp/behemoth', 'md5', -1),
            'linux': ('jms_cli_linux', '/tmp/behemoth', 'md5sum', 0),
            'windows': ('jms_cli_windows.exe', r'C:\Windows\Temp', '', 0),
        }
        filename, remote_dir, md5_cmd, md5_index = platform_named.get(str(self.base), ('', '', ''))
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

        if not (local_exist and len(stdout) > 0
                and get_file_md5(local_path) == stdout[md5_index].strip()):
            self.ssh_client.exec_command(f'mkdir -p {os.path.dirname(self._remote_script_path)}')
            self._scp(str(local_path), str(self._remote_script_path))

        print(p.info(f'【%s】%s' % (_('End'), _("Processing script file"))))

    def __process_commands_file(
            self, remote_commands_file: str, local_commands_file: str,
            token: str, **kwargs: dict
    ) -> None:
        print(p.info(f'【%s】%s' % (_('Start'), _("Processing command files"))))
        encrypted_data = kwargs.get('encrypted_data', False)
        if encrypted_data:
            local_commands_file = encrypt_json_file(local_commands_file, token[:32])

        remote_command_dir = os.path.dirname(remote_commands_file)
        self.ssh_client.exec_command(f'mkdir -p {remote_command_dir}')
        self._scp(local_commands_file, remote_commands_file, mode=0o400)
        if cmd_file := kwargs.pop('cmd_file_real', ''):
            cmd_filename = os.path.basename(cmd_file)
            self._scp(cmd_file, os.path.join(remote_command_dir, cmd_filename), mode=0o400)
        print(p.info(f'【%s】%s' % (_('End'), _("Processing command files"))))

    def __process_file(self, **kwargs: dict) -> None:
        self.__ensure_script_exist()
        self.__process_commands_file(**kwargs)

    def __clear(self, remote_commands_file: str, local_commands_file: str, **kwargs: dict) -> None:
        # 清理远端文件
        command = f'rm -f {remote_commands_file}'
        __, stdout, __ = self.ssh_client.exec_command(command)
        if stdout.channel.recv_exit_status() == 0:
            logger.warning(f'Remote file({remote_commands_file}) deletion failed')
        # 清理本地文件
        os.remove(local_commands_file)

    def __execute_cmd(self, **kwargs: dict) -> None:
        print(p.info(f'【%s】%s' % (_('Start'), _('Execute commands'))))
        revert_key = {'remote_commands_file': 'cmd_set_filepath'}
        exclude_params = ['local_commands_file', 'cmd_file_real']
        params = {revert_key.get(k, k): v for k, v in kwargs.items() if k not in exclude_params}
        logger.debug('Behemoth cmd params: %s' % params)
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
        print(p.info(f'【%s】%s' % (_('End'), _('Execute commands'))))

    def __execute(self, **kwargs: dict) -> None:
        self.__process_file(**kwargs)
        self.__execute_cmd(**kwargs)

    def run(self, run_params: dict) -> None:
        self.__execute(**run_params)
        # self.__clear(**run_params) # 先不清理了，稳定了再说


class Command(JMSOrgBaseModel):
    input = models.TextField(blank=True, verbose_name=_('Input'))
    output = models.CharField(max_length=1024, blank=True, verbose_name=_('Output'))
    index = models.IntegerField(db_index=True, verbose_name=_('Index'))
    status = models.CharField(max_length=32, default=CommandStatus.not_start, verbose_name=_('Status'))
    execution_id = models.CharField(max_length=36, verbose_name=_('Execution'))
    timestamp = models.IntegerField(default=0, db_index=True, verbose_name=_('Timestamp'))
    pause = models.BooleanField(default=False, verbose_name=_('Pause'))
    has_delete = models.BooleanField(default=False, verbose_name=_('Delete'))

    class Meta:
        verbose_name = _('Command')
        ordering = ('index',)

    def __str__(self):
        return f'{_("Command")}: {self.input[:10]}'

    def to_dict(self, extra=None):
        extra_fields = extra or []
        fields = ['input', 'pause'] + extra_fields
        return model_to_dict(self, fields=fields)


class Environment(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    assets = models.ManyToManyField('assets.Database', verbose_name=_("Assets"))

    def __str__(self):
        return self.name


class Playback(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    monthly_version = models.ForeignKey(
        'MonthlyVersion', on_delete=models.CASCADE, related_name='playbacks',
        null=True, verbose_name=_('Monthly version')
    )

    def create_pause(self, pause_data):
        execution = Execution.objects.create(name=_('Pause'), category=ExecutionCategory.pause)
        Command.objects.create(
            input=pause_data['input'], output=pause_data['output'], index=0,
            execution_id=execution.id, pause=True,
        )

        PlaybackExecution.objects.create(
            playback=self, execution=execution, plan_name=pause_data['input']
        )


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
    c_type = models.CharField(max_length=32, default='default', verbose_name=_('Custom type'))

    class Meta:
        verbose_name = _('Plan')
        ordering = ('-date_created',)

    def create_execution(self, with_auth=False, **other):
        request = get_current_request()
        params = {
            'user_id': request.user.id, 'plan': self, **other
        }
        if with_auth:
            params.update({'asset': self.asset, 'account': self.account})
        return Execution.objects.create(**params)

    @property
    def playback_executions(self):
        obj = ObjectExtend.objects.filter(obj_id=self.id).values('meta').first() or {'meta': {}} # noqa
        return obj['meta'].get('playback_executions', [])


class ObjectExtend(models.Model):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    obj_id = models.UUIDField(verbose_name=_('Model object'))
    meta = models.JSONField(default=dict, verbose_name=_('Meta'))
    category = models.CharField(max_length=128, verbose_name=_('Category'))

    class Meta:
        verbose_name = _('Object extend')


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
    asset_name = models.CharField(max_length=128, default='-', verbose_name=_('Asset name'))
    account_username = models.CharField(max_length=128, default='-', verbose_name=_('Account username'))
    user_id = models.CharField(max_length=36, verbose_name=_('User'))
    reason = models.CharField(max_length=512, default='-', verbose_name=_('Reason'))
    status = models.CharField(max_length=32, default=TaskStatus.not_start, verbose_name=_('Status'))
    task_id = models.CharField(max_length=36, default='', verbose_name=_('Task ID'))
    version = models.CharField(max_length=32, default='', blank=True, verbose_name=_('Version'))

    class Meta:
        verbose_name = _('Task')
        ordering = ('date_created',)

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


class PlaybackExecution(JMSOrgBaseModel):
    playback = models.ForeignKey(
        Playback, related_name='executions', on_delete=models.CASCADE, verbose_name=_('Playback')
    )
    execution = models.ForeignKey(Execution, on_delete=models.CASCADE, verbose_name=_('Execution'))
    plan_name = models.CharField(max_length=128, verbose_name=_('Plan name'))
    # asset_name, account_username
    meta = models.JSONField(default=dict, verbose_name=_('Meta'))

    class Meta:
        ordering = ('date_created',)


class MonthlyVersion(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))


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
