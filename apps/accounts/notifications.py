import os

from django.utils.translation import gettext_lazy as _

from common.tasks import send_mail_attachment_async, send_file_to_asset_by_ansible
from users.models import User


class AccountBackupExecutionTaskMsg(object):
    subject = _('Notification of account backup route task results')

    def __init__(self, name: str, user: User = None, ansible_info: dict = None):
        self.name = name
        self.user = user
        self.ansible_info = ansible_info

    @property
    def message(self):
        name = self.name
        if self.user.secret_key:
            return _('{} - The account backup passage task has been completed.'
                     ' See the attachment for details').format(name)
        else:
            return _("{} - The account backup passage task has been completed: "
                     "the encryption password has not been set - "
                     "please go to personal information -> file encryption password "
                     "to set the encryption password").format(name)

    def publish(self, attachment_list=None):
        if self.user:
            send_mail_attachment_async(
                self.subject, self.message, [self.user.email], attachment_list
            )
        if self.ansible_info:
            send_file_to_asset_by_ansible(**self.ansible_info)


class ChangeSecretExecutionTaskMsg(object):
    subject = _('Notification of implementation result of encryption change plan')

    def __init__(self, name: str, user: User):
        self.name = name
        self.user = user

    @property
    def message(self):
        name = self.name
        if self.user.secret_key:
            return _('{} - The encryption change task has been completed. '
                     'See the attachment for details').format(name)
        else:
            return _("{} - The encryption change task has been completed: the encryption "
                     "password has not been set - please go to personal information -> "
                     "file encryption password to set the encryption password").format(name)

    def publish(self, attachments=None):
        send_mail_attachment_async(
            self.subject, self.message, [self.user.email], attachments
        )
