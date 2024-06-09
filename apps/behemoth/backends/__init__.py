from importlib import import_module

from django.conf import settings
from django.utils.functional import LazyObject


def get_command_storage():
    config = settings.BEHEMOTH_COMMAND_STORAGE_ES
    module = 'es' if config else 'db'
    engine_class = import_module(f'behemoth.backends.{module}')
    return engine_class.CommandStore(config)


class CommandStorage(LazyObject):
    def _setup(self):
        self._wrapped = get_command_storage()


cmd_storage = CommandStorage()
