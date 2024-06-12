import base64
import os
import json

import paramiko

from typing import Callable

from django.utils.translation import gettext as _
from django.conf import settings
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import models
from paramiko.ssh_exception import SSHException

from accounts.models import Account
from assets.models import Host, Protocol, Asset, Platform
from assets.const import Protocol as const_p, WORKER_NAME
from common.utils import get_logger
from common.exceptions import JMSException
from jumpserver.settings import get_file_md5
from orgs.mixins.models import JMSOrgBaseModel
from orgs.mixins.models import OrgManager
from users.models import User
from .const import TaskStatus, CommandStatus, PlanStrategy, PlanCategory
from .utils import encrypt_json_file


logger = get_logger(__name__)


class WorkerQuerySet(OrgManager):
    def get_queryset(self):
        return super().get_queryset().filter(platform__name=WORKER_NAME)

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False):
        default_platform = Worker.default_platform()
        for obj in objs:
            obj.platform = default_platform
        return super().bulk_create(objs, batch_size, ignore_conflicts)


class Worker(Host):
    accounts: models.QuerySet
    protocols: models.QuerySet
    objects = WorkerQuerySet()

    class Meta:
        proxy = True
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
        self._callback: Callable | None = None

    def save(self, *args, **kwargs):
        self.platform = self.default_platform()
        return super().save(*args, **kwargs)

    @classmethod
    def default_platform(cls):
        return Platform.objects.get(name=WORKER_NAME, internal=True) # noqa

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

    def test_connectivity(self, immediate_disconnect=True) -> bool:
        connectivity: bool = False
        try:
            account: Account = self.get_account()
        except Exception as error:
            logger.error(f'Task worker set account failed: {error}')
            return False

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self.address, port=self.get_target_ssh_port(),
                username=account.username, password=account.password
            )
            connectivity = True
            if not immediate_disconnect:
                self._ssh_client = client
            else:
                client.close()
        except Exception as error:
            logger.error(f'Task worker test ssh connect failed: {error}')
        return connectivity

    def _scp(self, local_path: str, remote_path: str, mode=0o544) -> None:
        sftp = self._ssh_client.open_sftp()
        try:
            sftp.remove(remote_path)
        except IOError:
            pass
        sftp.put(local_path, remote_path)
        sftp.chmod(remote_path, mode)
        sftp.close()

    def __ensure_script_exist(self) -> None:
        self._callback('正在处理脚本文件')
        platform_named = {
            'mac': ('jms_cli_mac', '/tmp/behemoth'),
            'linux': ('jms_cli_linux', '/tmp/behemoth'),
            'windows': ('jms_cli_windows.exe', r'C:\Windows\Temp'),
        }
        filename, remote_dir = platform_named.get(self.type, ('', ''))
        if not filename:
            raise JMSException(_('The worker[%s](%s) type error') % (self, self.type))

        remote_path = os.path.join(remote_dir, filename)
        local_path = os.path.join(
            settings.APPS_DIR, 'behemoth', 'libs', 'go_script', filename
        )
        command = f'md5sum {remote_path}'
        __, stdout, __ = self._ssh_client.exec_command(command)
        stdout = stdout.read().decode().split()
        local_exist = os.path.exists(local_path)

        if local_exist and len(stdout) > 0 and get_file_md5(local_path) == stdout[0].strip():
            return

        self._remote_script_path = remote_path
        self._ssh_client.exec_command(f'mkdir -p {os.path.dirname(remote_path)}')
        self._scp(local_path, self._remote_script_path)

    def __process_commands_file(
            self, remote_commands_file: str, local_commands_file: str, token: str, **kwargs: dict
    ) -> None:
        self._callback('正在生成命令文件')
        encrypted_data = kwargs.get('encrypted_data', False)
        if encrypted_data:
            local_commands_file = encrypt_json_file(local_commands_file, token[:32])

        self._ssh_client.exec_command(f'mkdir -p {os.path.dirname(remote_commands_file)}')
        self._scp(local_commands_file, remote_commands_file, mode=0o400)

    def __process_file(self, **kwargs: dict) -> None:
        self.__ensure_script_exist()
        self.__process_commands_file(**kwargs)

    def __clear(self, remote_commands_file: str, local_commands_file: str, **kwargs: dict) -> None:
        # 清理远端文件
        command = f'rm -f {remote_commands_file}'
        __, stdout, __ = self._ssh_client.exec_command(command)
        if stdout.channel.recv_exit_status() == 0: # TODO 这里要改一下，状态码判断有问题
            logger.warning(f'Remote file({remote_commands_file}) deletion failed')
        # 清理本地文件
        os.remove(local_commands_file)

    def __execute_cmd(self, **kwargs: dict) -> None:
        self._callback('正在下发命令')
        revert_key = {'remote_commands_file': 'cmd_filepath'}
        params = {revert_key.get(k, k): v for k, v in kwargs.items()}
        encoded_data = base64.b64encode(json.dumps(params).encode()).decode()
        try:
            __, stdout, __ = self._ssh_client.exec_command(
                f'{self._remote_script_path} --command {encoded_data} --backend'
            )
            self._callback('任务已下发: %s' % (stdout.read().decode() or _('Success')))
        except SSHException as e:
            raise JMSException(str(e))

    def __execute(self, **kwargs: dict) -> None:
        self.__process_file(**kwargs)
        self.__execute_cmd(**kwargs)

    def run(self, run_params: dict, callback: Callable) -> None:
        self._callback = callback
        self.__execute(**run_params)
        # self.__clear(**run_params) # TODO 后续放开


class Command(JMSOrgBaseModel):
    input = models.CharField(max_length=1024, blank=True, verbose_name=_('Input'))
    output = models.CharField(max_length=1024, blank=True, verbose_name=_('Output'))
    index = models.IntegerField(db_index=True, verbose_name=_('Index'))
    status = models.CharField(max_length=32, default=CommandStatus.waiting, verbose_name=_('Status'))
    execution_id = models.CharField(max_length=36, verbose_name=_('Execution'))
    timestamp = models.IntegerField(default=0, db_index=True)

    class Meta:
        verbose_name = _('Command')
        ordering = ('index', )


class Environment(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    assets = models.ManyToManyField('assets.Asset', verbose_name=_("Assets"))


class Playback(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name='playbacks',
        null=True, verbose_name=_('Environment')
    )


class Plan(JMSOrgBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    strategy = models.CharField(
        max_length=32, default=PlanStrategy.failed_stop,
        choices=PlanStrategy.choices, verbose_name=_('Strategy')
    )
    category = models.CharField(
        max_length=32, default=PlanCategory.deploy,
        choices=PlanCategory.choices, verbose_name=_('Category')
    )
    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name='instructions', verbose_name=_('Environment')
    )
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, verbose_name=_('Asset'))
    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name=_('Account'))
    playback = models.ForeignKey(Playback, on_delete=models.CASCADE, verbose_name=_('Playback'))

    class Meta:
        verbose_name = _('Plan')

    def create_execution(self, user):
        plan_meta ={
            'strategy': self.strategy
        }
        return Execution.objects.create(
            plan_id=self.id, asset=self.asset, user_id=user.id,
            account=self.account, plan_meta=plan_meta
        )

    @property
    def execution(self):
        return Execution.objects.filter(plan_id=self.id).first()


class Execution(JMSOrgBaseModel):
    worker = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, related_name='e1s', verbose_name=_('Worker')
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, null=True, related_name='e2s', verbose_name=_('Asset')
    )
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, verbose_name=_('Account'))
    plan_id = models.CharField(max_length=36, verbose_name=_('Plan'))
    plan_meta = models.JSONField(default=dict, verbose_name=_('Plan meta'))
    user_id = models.CharField(max_length=36, verbose_name=_('User'))
    reason = models.CharField(max_length=512, default='-', verbose_name=_('Reason'))
    status = models.CharField(max_length=32, default=TaskStatus.not_started, verbose_name=_('Status'))

    class Meta:
        verbose_name = _('Task')
        ordering = ['-date_created']

    @property
    def user(self):
        err = _('User not found')
        if not self.user_id:
            raise JMSException(err)

        u = User.objects.filter(id=self.user_id).first()
        if not u:
            raise JMSException(err)
        return u

    def get_commands(self):
        # TODO 这里后边要搞成ES的
        return Command.objects.filter(execution_id=self.id)


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
