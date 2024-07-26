from importlib import import_module

from django.conf import settings
from django.utils.functional import LazyObject


TYPE_ENGINE_MAPPING = {
    'db': 'audits.backends.db',
    'es': 'audits.backends.es',
}


def get_operate_log_storage(default=False):
    engine_mod = import_module(TYPE_ENGINE_MAPPING['db'])
    es_config = settings.OPERATE_LOG_ELASTICSEARCH_CONFIG
    if not default and es_config:
        engine_mod = import_module(TYPE_ENGINE_MAPPING['es'])
    storage = engine_mod.OperateLogStore(es_config)
    return storage


class OperateLogStorage(LazyObject):
    def _setup(self):
        self._wrapped = get_operate_log_storage()


operate_log_storage = OperateLogStorage()
