import re

from django.db import models
from django.utils.translation import gettext as _


PAUSE_RE_PATTERN = r'FORMAT PAUSE | NAME:(\w+) \| DESCRIBE:(\w+) \| PAUSE:(\w+);'
PAUSE_RE = re.compile(PAUSE_RE_PATTERN)
FORMAT_COMMAND_CACHE_KEY = 'format-command-cache-{}'
FILE_COMMAND_CACHE_KEY = 'command:pause:{}'


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


class CommandCategory(models.TextChoices):
    command = 'command', _('Command')
    pause = 'pause', _('Pause')
    file = 'file', _('File')


class PlanCategory(models.TextChoices):
    sync = 'sync', _('Sync')
    deploy = 'deploy', _('Deploy')
