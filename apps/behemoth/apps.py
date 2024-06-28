import os

from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class BehemothConfig(AppConfig):
    name = 'behemoth'
    verbose_name = _('Behemoth')

    def ready(self):
        from . import signal_handlers  # noqa
        from . import tasks  # noqa

        os.makedirs(settings.BEHEMOTH_DIR, exist_ok=True)
        super().ready()
