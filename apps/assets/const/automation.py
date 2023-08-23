from django.db.models import TextChoices
from django.utils.translation import ugettext_lazy as _


class Connectivity(TextChoices):
    UNKNOWN = '-', _('Unknown')
    OK = 'ok', _('Ok')
    ERR = 'err', _('Error')

    @classmethod
    def get_label(cls, k):
        label = dict(cls.choices).get(k)
        return label


class AutomationTypes(TextChoices):
    ping = 'ping', _('Ping')
    ping_gateway = 'ping_gateway', _('Ping gateway')
    gather_facts = 'gather_facts', _('Gather facts')

    @classmethod
    def get_type_model(cls, tp):
        from assets.models import (
            PingAutomation, GatherFactsAutomation,
        )
        type_model_dict = {
            cls.ping: PingAutomation,
            cls.gather_facts: GatherFactsAutomation,
        }
        return type_model_dict.get(tp)
