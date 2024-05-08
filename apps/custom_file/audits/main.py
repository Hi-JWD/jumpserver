# data/audits/main.py
import os
import time
import json

from datetime import datetime

import requests

from django.conf import settings
from django.core.cache import cache

from users.utils import JobUtil
from common.utils import get_logger
from common.db.encoder import ModelJSONFieldEncoder


logger = get_logger(__name__)


def time_parser(datatime_str):
    if not datatime_str:
        return ''
    td = datetime.strptime(datatime_str, '%Y/%m/%d %H:%M:%S +0800')
    return td.strftime('%Y%m%d%H%M')


os.makedirs(os.path.join(settings.DATA_DIR, 'audits'), exist_ok=True)
FAILED_REQUEST_FILE = os.path.join(settings.DATA_DIR, 'audits', 'audits_callback_failed.txt')
CACHE_FIELDS = [('id', str), ('date_start', time_parser), ('date_end', time_parser)]


def audit_callback(category, data):
    if category == 'host_session_log' and settings.AUDIT_CALLBACK_URL:
        key = ''.join([method(data[field]) for field, method in CACHE_FIELDS])
        if cache.get(key):
            return

        for i in range(3):
            try:
                data['job_id'] = JobUtil(data['user_id']).get_job()
                body = json.dumps(data, cls=ModelJSONFieldEncoder)
                resp = requests.post(settings.AUDIT_CALLBACK_URL, json=body)
                error = resp.status_code != 200
                logger.info(f'Status code {resp.status_code}')
            except Exception as err:
                logger.error(f'Audit callback failed: {err}')
                error = True
            if error:
                time.sleep(5)
            else:
                key = ''.join([method(data[field]) for field, method in CACHE_FIELDS])
                cache.set(key, 1, timeout=60)
                break
        else:
            with open(FAILED_REQUEST_FILE, 'a') as f:
                f.write(str(data))
