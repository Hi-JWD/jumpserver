from django.db import models
from django.utils.translation import gettext as _


class TaskStatus(models.TextChoices):
    not_started = 'not_started'
    executing = 'executing'
    pause = 'pause'
    success = 'success'
    failed = 'failed'


class CommandStatus(models.TextChoices):
    waiting = 'waiting'
    success = 'success'
    failed = 'failed'


class PlanStrategy(models.TextChoices):
    failed_continue = 'failed_continue', _('Failed continue')
    failed_stop = 'failed_stop', _('Failed stop')


class PlanCategory(models.TextChoices):
    sync = 'sync', _('Sync')
    deploy = 'deploy', _('Deploy')
