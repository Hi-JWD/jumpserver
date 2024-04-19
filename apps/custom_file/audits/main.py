# data/audits/main.py
import os
import time

import requests

from django.conf import settings

from users.utils import JobUtil
from common.utils import get_logger


logger = get_logger(__name__)


os.makedirs(os.path.join(settings.DATA_DIR, 'audits'), exist_ok=True)
FAILED_REQUEST_FILE = os.path.join(settings.DATA_DIR, 'audits', 'audits_callback_failed.txt')


def audit_callback(category, data):
    if category == 'host_session_log' and settings.AUDIT_CALLBACK_URL:
        for i in range(3):
            try:
                data['job_id'] = JobUtil(data['user_id']).get_job()
                resp = requests.post(settings.AUDIT_CALLBACK_URL, json=data)
                error = resp.status_code != 200
            except Exception: # noqa
                error = True
            if error:
                time.sleep(5)
            else:
                break
        else:
            with open(FAILED_REQUEST_FILE, 'a') as f:
                f.write(str(data))
