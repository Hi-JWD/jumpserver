import json
import os
import shutil
import time
import yaml

from collections import defaultdict, OrderedDict

from django.conf import settings
from django.utils import timezone
from openpyxl import Workbook
from rest_framework import serializers

from accounts.notifications import AccountBackupExecutionTaskMsg
from accounts.serializers import AccountSecretSerializer
from accounts.automations.methods import BASE_DIR as AUTOMATION_BASE_DIR
from assets.models import Asset
from assets.const import AllTypes
from common.utils import lazyproperty
from common.utils.file import encrypt_and_compress_zip_file
from common.utils.timezone import local_now_display
from users.models import User
from common.utils import get_logger


logger = get_logger(__file__)

PATH = os.path.join(os.path.dirname(settings.BASE_DIR), 'tmp')


class BaseAccountHandler:
    @classmethod
    def unpack_data(cls, serializer_data, data=None):
        if data is None:
            data = {}
        for k, v in serializer_data.items():
            if isinstance(v, OrderedDict):
                cls.unpack_data(v, data)
            else:
                data[k] = v
        return data

    @classmethod
    def get_header_fields(cls, serializer: serializers.Serializer):
        try:
            backup_fields = getattr(serializer, 'Meta').fields_backup
        except AttributeError:
            backup_fields = serializer.fields.keys()
        header_fields = {}
        for field in backup_fields:
            v = serializer.fields[field]
            if isinstance(v, serializers.Serializer):
                _fields = cls.get_header_fields(v)
                header_fields.update(_fields)
            else:
                header_fields[field] = str(v.label)
        return header_fields

    @classmethod
    def create_row(cls, data, header_fields):
        data = cls.unpack_data(data)
        row_dict = {}
        for field, header_name in header_fields.items():
            row_dict[header_name] = str(data.get(field, field))
        return row_dict

    @classmethod
    def add_rows(cls, data, header_fields, sheet):
        data_map = defaultdict(list)
        for i in data:
            row = cls.create_row(i, header_fields)
            if sheet not in data_map:
                data_map[sheet].append(list(row.keys()))
            data_map[sheet].append(list(row.values()))
        return data_map


class AssetAccountHandler(BaseAccountHandler):
    @staticmethod
    def get_filename(plan_name):
        filename = os.path.join(
            PATH, f'{plan_name}-{local_now_display()}-{time.time()}.xlsx'
        )
        return filename

    @staticmethod
    def handler_secret(data, section):
        for account_data in data:
            secret = account_data.get('secret')
            if not secret:
                continue
            length = len(secret)
            index = length // 2
            if section == "front":
                secret = secret[:index] + '*' * (length - index)
            elif section == "back":
                secret = '*' * (length - index) + secret[index:]
            account_data['secret'] = secret

    @classmethod
    def create_data_map(cls, accounts, section):
        data_map = defaultdict(list)

        if not accounts.exists():
            return data_map

        type_dict = {}
        for i in AllTypes.grouped_choices_to_objs():
            for j in i['children']:
                type_dict[j['value']] = j['display_name']

        header_fields = cls.get_header_fields(AccountSecretSerializer(accounts.first()))
        account_type_map = defaultdict(list)
        for account in accounts:
            account_type_map[account.type].append(account)

        data_map = {}
        for tp, _accounts in account_type_map.items():
            sheet_name = type_dict.get(tp, tp)
            data = AccountSecretSerializer(_accounts, many=True).data
            cls.handler_secret(data, section)
            data_map.update(cls.add_rows(data, header_fields, sheet_name))

        print('\n\033[33m- 共备份 {} 条账号\033[0m'.format(accounts.count()))
        return data_map


class AccountBackupHandler:
    def __init__(self, execution):
        self.execution = execution
        self.plan_name = self.execution.plan.name
        self.is_frozen = False  # 任务状态冻结标志
        self._complete_file = None
        self._front_file = None
        self._back_file = None
        self._all_files = []

    @property
    def complete_file(self):
        if self._complete_file is None:
            self._complete_file = self.create_excel()
        return self._complete_file

    @property
    def front_file(self):
        if self._front_file is None:
            self._front_file = self.create_excel('front')
        return self._front_file

    @property
    def back_file(self):
        if self._back_file is None:
            self._back_file = self.create_excel('back')
        return self._back_file

    def create_excel(self, section='complete'):
        print(
            '\n'
            '\033[32m>>> 正在生成资产或应用相关备份信息文件\033[0m'
            ''
        )
        # Print task start date
        time_start = time.time()
        files = []
        accounts = self.execution.backup_accounts
        data_map = AssetAccountHandler.create_data_map(accounts, section)
        if not data_map:
            return files

        filename = AssetAccountHandler.get_filename(self.plan_name)

        wb = Workbook(filename)
        for sheet, data in data_map.items():
            ws = wb.create_sheet(str(sheet))
            for row in data:
                ws.append(row)
        wb.save(filename)
        files.append(filename)
        timedelta = round((time.time() - time_start), 2)
        print('步骤完成: 用时 {}s'.format(timedelta))
        self._all_files.extend(files)
        return files

    def prepare_runtime_dir(self):
        ansible_dir = settings.ANSIBLE_DIR
        task_name = self.execution.snapshot['name']
        dir_name = '{}_{}'.format(task_name.replace(' ', '_'), self.execution.id)
        path = os.path.join(
            ansible_dir, 'automations', self.execution.snapshot['type'],
            dir_name, timezone.now().strftime('%Y%m%d_%H%M%S')
        )
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True, mode=0o755)
        return path

    @lazyproperty
    def runtime_dir(self):
        path = self.prepare_runtime_dir()
        if settings.DEBUG_DEV:
            msg = 'Ansible runtime dir: {}'.format(path)
            print(msg)
        return path

    def _get_inventory_path(self, asset_info):
        path = os.path.join(self.runtime_dir, asset_info['platform_name'], 'hosts.json')
        path_dir = os.path.dirname(path)
        if not os.path.exists(path_dir):
            os.makedirs(path_dir, 0o700, True)

        if asset_info['secret_type'] == 'ssh_key':
            auth_params = {
                'ansible_ssh_private_key_file': asset_info['secret_key']
            }
        else:
            auth_params = {'ansible_password': asset_info['secret']}

        data = {
            'all': {
                'hosts': {
                    asset_info['name']: {**auth_params, **{
                        'ansible_connection': 'ssh',
                        'ansible_host': asset_info['host'],
                        'ansible_port': asset_info['port'],
                        'ansible_user': asset_info['username'],
                        'params': {
                            'file_list': [
                                {
                                    'src': p, 'dest': os.path.join(
                                        asset_info['sftp_home'], os.path.basename(p)
                                    )
                                } for p in asset_info['src_path']
                            ]
                        }
                    }}
                }
            }
        }
        with open(path, 'w') as f:
            f.write(json.dumps(data, indent=4))
        return path

    def _get_playbook_path(self, asset_info):
        path = os.path.join(self.runtime_dir, asset_info['platform_name'])
        sub_playbook_path = os.path.join(path, 'project', 'main.yml')
        method_playbook_dir_path = os.path.join(AUTOMATION_BASE_DIR, 'backup_account', 'host', 'posix')
        shutil.copytree(method_playbook_dir_path, os.path.dirname(sub_playbook_path))

        with open(sub_playbook_path, 'r') as f:
            plays = yaml.safe_load(f)
        for play in plays:
            play['hosts'] = 'all'

        with open(sub_playbook_path, 'w') as f:
            yaml.safe_dump(plays, f)
        return sub_playbook_path

    def send_backup_mail(self, files, recipients):
        if not files:
            return
        recipients = User.objects.filter(id__in=list(recipients))
        print('\n\033[32m>>> 发送备份邮件\033[0m')
        plan_name = self.plan_name
        for user in recipients:
            if not user.secret_key:
                attachment_list = []
            else:
                password = user.secret_key.encode('utf8')
                attachment = os.path.join(PATH, f'{plan_name}-{local_now_display()}-{time.time()}.zip')
                encrypt_and_compress_zip_file(attachment, password, files)
                self._all_files.append(attachment)
                attachment_list = [attachment, ]
            AccountBackupExecutionTaskMsg(plan_name, user).publish(attachment_list)
            print('邮件已发送至{}({})'.format(user, user.email))

    @staticmethod
    def _get_asset_info(asset):
        account = asset.accounts.all().order_by('-privileged').first()
        protocol = asset.protocols.filter(name='sftp').first()
        if not account or not protocol:
            return None

        asset_info = {
            'name': asset.name, 'host': asset.address, 'port': protocol.port or 22,
            'username': account.username, 'secret': account.secret,
            'secret_key': account.private_key_path,
            'secret_type': account.secret_type,
            'platform_name': asset.platform.name,
            'sftp_home': protocol.setting.get('sftp_home', '/tmp')
        }
        return asset_info

    def _get_ansible_info(self, asset_info):
        return {
            'inventory': self._get_inventory_path(asset_info),
            'playbook': self._get_playbook_path(asset_info),
            'project_dir': self.runtime_dir
        }

    def send_backup_asset(self, files, receiving_assets):
        if not files:
            return
        receiving_assets = Asset.objects.filter(id__in=list(receiving_assets))
        print('\n\033[32m>>> 通过SFTP发送文件\033[0m')
        plan_name = self.plan_name
        for asset in receiving_assets:
            asset_info = self._get_asset_info(asset)
            if not asset_info:
                continue

            password = asset_info['secret'][:32].encode('utf8')  # 切割目的是防止资产认证为密钥时，密码过长不好手动解密
            attachment = os.path.join(PATH, f'{plan_name}-{local_now_display()}-{time.time()}.zip')
            encrypt_and_compress_zip_file(attachment, password, files)
            self._all_files.append(attachment)
            attachment_list = [attachment, ]

            asset_info['src_path'] = attachment_list
            ansible_info = self._get_ansible_info(asset_info)

            AccountBackupExecutionTaskMsg(plan_name, ansible_info=ansible_info).publish(attachment_list)
            print('邮件已发送至{}({})'.format(asset_info['host'], asset_info['username']))

    def step_perform_task_update(self, is_success, reason):
        self.execution.reason = reason[:1024]
        self.execution.is_success = is_success
        self.execution.save()
        print('已完成对任务状态的更新')

    def step_finished(self, is_success):
        if is_success:
            print('任务执行成功')
        else:
            print('任务执行失败')

        for file in self._all_files:
            try:
                os.remove(file)
            except Exception as err:
                logger.error(f'Delete file failed: {err}')

    def _run(self):
        is_success = False
        error = '-'
        try:
            recipients_part_one = self.execution.snapshot.get('recipients_part_one', [])
            recipients_part_two = self.execution.snapshot.get('recipients_part_two', [])
            receiving_asset_one = self.execution.snapshot.get('receiving_asset_one', [])
            receiving_asset_two = self.execution.snapshot.get('receiving_asset_two', [])
            if not any((
                    recipients_part_one, recipients_part_two,
                    receiving_asset_one, receiving_asset_two)):
                print('\n\033[32m>>> 该备份任务未分配收件方式\033[0m')

            if recipients_part_one and recipients_part_two:
                self.send_backup_mail(self.front_file, recipients_part_one)

                self.send_backup_mail(self.back_file, recipients_part_two)
            else:
                recipients = recipients_part_one or recipients_part_two
                self.send_backup_mail(self.complete_file, recipients)

            if receiving_asset_one and receiving_asset_two:
                self.send_backup_asset(self.front_file, receiving_asset_one)

                self.send_backup_asset(self.back_file, receiving_asset_two)
            else:
                receiving_assets = receiving_asset_one or receiving_asset_two
                self.send_backup_asset(self.complete_file, receiving_assets)
        except Exception as e:
            self.is_frozen = True
            print('任务执行被异常中断')
            print('下面打印发生异常的 Traceback 信息 : ')
            print(e)
            error = str(e)
        else:
            is_success = True
        finally:
            reason = error
            self.step_perform_task_update(is_success, reason)
            self.step_finished(is_success)

    def run(self):
        print('任务开始: {}'.format(local_now_display()))
        time_start = time.time()
        try:
            self._run()
        except Exception as e:
            print('任务运行出现异常')
            print('下面显示异常 Traceback 信息: ')
            print(e)
        finally:
            print('\n任务结束: {}'.format(local_now_display()))
            timedelta = round((time.time() - time_start), 2)
            print('用时: {}'.format(timedelta))
