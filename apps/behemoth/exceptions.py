from django.utils.translation import gettext_lazy as _

from common.exceptions import JMSException


class PauseException(JMSException):
    default_detail = _('Pause')
