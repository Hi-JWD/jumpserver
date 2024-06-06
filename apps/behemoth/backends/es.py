# -*- coding: utf-8 -*-
#
import pytz

from datetime import datetime

from common.utils import get_logger
from common.plugins.es import ES


logger = get_logger(__file__)


class CommandStore(ES):
    def __init__(self, config):
        properties = {
            "task_id": {
                "type": "keyword"
            },
            "org_id": {
                "type": "keyword"
            },
            "@timestamp": {
                "type": "date"
            },
            "timestamp": {
                "type": "long"
            }
        }
        exact_fields = {}
        match_fields = {'input', 'output'}
        keyword_fields = {'task_id', 'org_id'}
        super().__init__(config, properties, keyword_fields, exact_fields, match_fields)

    def make_data(self, command):
        date = datetime.fromtimestamp(command['timestamp'], tz=pytz.UTC)
        return {
            'input': command['input'], 'output': command['output'],
            'task_id': command['task_id'], 'timestamp': command['timestamp'],
            'org_id': command['org_id'],  'date': date
        }

    @staticmethod
    def handler_time_field(data):
        timestamp__gte = data.get('timestamp__gte')
        timestamp__lte = data.get('timestamp__lte')
        timestamp_range = {}

        if timestamp__gte:
            timestamp_range['gte'] = timestamp__gte
        if timestamp__lte:
            timestamp_range['lte'] = timestamp__lte
        return 'timestamp', timestamp_range
