import requests

from collections import OrderedDict
from collections.abc import Iterable

from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from common.exceptions import JMSException
from common.utils import get_logger

from .base import BaseSMSClient


logger = get_logger(__file__)


class GuangdaSmsClient(object):
    def __init__(self, host, account, channel_code, class_code):
        self.host = host[:-1] if host.endswith('/') else host
        self.account = account
        self.channel_code = channel_code
        self.class_code = class_code
        self.template_code = ''
        self.template_param = None
        self.phone_numbers_string = ''

    @property
    def content(self):
        if not self.template_param:
            raise ValueError('template_param can not be empty.')
        message = self.template_param.get('message')
        if message is None:
            code = self.template_param.get('code')
            message = self.template_code.replace('{code}', code)
        return message

    def _build_header(self):
        return {
            'seqId': '', 'enc': '0', 'account': self.account,
            'channelCode': self.channel_code, 'classCode': self.class_code,
            'organCode': '100000'
        }

    def _build_body(self):
        return {
            'token': '', 'timestamp': '', 'sendType': '0', 'sendTime': '',
            'longId': '', 'priority': '1', 'isTemplate': '0',
            'desAddress': self.phone_numbers_string, 'content': self.content
        }

    def set_phone_numbers(self, phone_numbers):
        if phone_numbers and isinstance(phone_numbers, Iterable):
            self.phone_numbers_string = '|'.join(phone_numbers)

    def set_template_code(self, template_code):
        if template_code:
            self.template_code = template_code

    def set_template_param(self, template_param):
        if template_param:
            self.template_param = template_param

    def send_sms(self):
        url = '%s/SERVICE_HTTP/submitJsonMessage' % self.host
        headers = self._build_header()
        body = self._build_body()
        resp = requests.post(url, headers=headers, json=body)
        return resp.json()


class GuangdaSMS(BaseSMSClient):
    SIGN_AND_TMPL_SETTING_FIELD_PREFIX = 'GUANGDA'

    @classmethod
    def new_from_settings(cls):
        return cls(
            host=settings.GUANGDA_HOST,
            account=settings.GUANGDA_ACCOUNT,
            channel_code=settings.GUANGDA_CHANNEL_CODE,
            class_code=settings.GUANGDA_CLASS_CODE,
        )

    def __init__(self, host, account: str, channel_code: str, class_code: str):
        self.client = GuangdaSmsClient(host, account, channel_code, class_code)

    def send_sms(
            self, phone_numbers: list, template_code: str, template_param: OrderedDict, **kwargs
    ):
        try:
            logger.info(f'Guangda sms send: '
                        f'phone_numbers={phone_numbers} '
                        f'template_code={template_code} '
                        f'template_param={template_param}')

            self.client.set_phone_numbers(phone_numbers)
            self.client.set_template_code(template_code)
            self.client.set_template_param(template_param)

            resp = self.client.send_sms()
            if resp.get('code', '999') != '0':
                raise JMSException(code='response_bad', detail=resp.get('message', _('Unknown')))
        except Exception as err:
            raise JMSException(code='response_bad', detail=err)

    @staticmethod
    def need_pre_check():
        return False


client = GuangdaSMS
