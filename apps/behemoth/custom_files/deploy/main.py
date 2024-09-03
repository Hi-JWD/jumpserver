import uuid
import time

import requests

from django.utils.translation import gettext_lazy as _

from behemoth.models import Environment, Playback, Plan
from orgs.utils import current_org


class Client(object):
    def __init__(self):
        self.convert_fields = {
            'summary': 'comment', 'param_env_name': 'environment',
            'param_banben': 'playback', 'name': 'name'
        }
        self.i18n_map = {
            'environment': _('Environment'), 'playback': _('Playback')
        }
        self.environment_map = {}
        self.playback_map = {}

    def get_obj(self, name, value):
        real_name, real_value = self.convert_fields[name], value
        if real_name == 'environment':
            real_value = self.environment_map.get(value)
            if not real_value:
                if obj := Environment.objects.filter(name=value).first():
                    real_value = {'id': obj.id, 'name': obj.name}
                    self.environment_map[real_name] = real_value
        elif real_name == 'playback':
            real_value = self.playback_map.get(value)
            if not real_value:
                if obj := Playback.objects.filter(name=value).first():
                    real_value = {'id': obj.id, 'name': obj.name}
                    self.playback_map[real_name] = real_value
        return real_name, real_value

    @staticmethod
    def _get_remote():
        try:
            login_url = 'http://22.21.20.17/login/'
            refresh_task_url = 'http://22.21.20.17/Api_banben/?flag=sitbanben'
            task_url = 'http://22.21.20.17/Api_Jirabanben/?flag=SIT&_=%s' % int(time.time())
            session = requests.Session()
            data = {'phone': '1xxxxxxxxxx', 'password': 'password'}
            session.post(login_url, data=data)
            session.get(refresh_task_url)
            response = session.get(task_url)
            result = response.json()['rows']
        except Exception as e:
            raise ValueError('Response error: %s' % e)
        return result

    def get(self):
        new_result = []
        for item in self._get_remote():
            if not item.get('param_env_name'):
                continue
            if Plan.objects.filter(name=item['name'], org_id=current_org.id).exists():
                continue

            new_item = {
                'id': str(uuid.uuid4()), 'c_type': 'default', 'selectable': True,
                'plan_strategy': 'failed_stop', 'playback_strategy': 'auto', 'tip': []
            }
            for k in self.convert_fields.keys():
                old_value = item.get(k)
                name, value = self.get_obj(k, old_value)
                new_item[name] = value or '-'
                if not value and name in self.i18n_map:
                    i18n_name = self.i18n_map[name]
                    new_item['tip'].append(f'系统中不存在名称为 [{old_value}] 的 [{i18n_name}] ')
                    new_item['selectable'] = False
            new_result.append(new_item)
        return new_result


handle_remote_pull = Client().get
