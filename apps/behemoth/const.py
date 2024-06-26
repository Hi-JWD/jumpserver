import re

from django.db import models
from django.utils.translation import gettext as _


PAUSE_RE_PATTERN = r'NAME:(.*?)\s*\|\s*DESCRIBE:(.*?)\s*\|\s*PAUSE:(.*?);'
PAUSE_RE = re.compile(PAUSE_RE_PATTERN)
FORMAT_COMMAND_CACHE_KEY = 'format-command-cache-{}'
FILE_COMMAND_CACHE_KEY = 'command:pause:{}'
TASK_TYPE_CACHE_KEY = 'task-info-type:{}'
TASK_DATA_CACHE_KEY = 'task-info-data:{}'


class TaskStatus(models.TextChoices):
    not_start = 'not_start'
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


class PlaybackStrategy(models.TextChoices):
    auto = 'auto', _('Auto add')
    manual = 'manual', _('Manual add')
    never = 'never', _('Never add')


class CommandCategory(models.TextChoices):
    command = 'command', _('Command')
    pause = 'pause', _('Pause')
    file = 'file', _('File')


class WorkerPlatform(models.TextChoices):
    linux = 'linux', _('Linux')
    mac = 'mac', _('Mac')


class PlanCategory(models.TextChoices):
    sync = 'sync', _('Sync')
    deploy = 'deploy', _('Deploy')
