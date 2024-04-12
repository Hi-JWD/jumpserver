# data/audits/main.py

import requests

from django.conf import settings

from users.utils import JobUtil
from common.utils import get_logger


logger = get_logger(__name__)


def audit_callback(category, data):
    if category == 'host_session_log' and settings.AUDIT_CALLBACK_URL:
        try:
            data['job_id'] = JobUtil(data['user_id']).get_job()
            resp = requests.post(settings.AUDIT_CALLBACK_URL, json=data)
            error = resp.status_code != 200
        except Exception: # noqa
            error = True

        if error:
            # TODO 考虑失败情况，最终失败落入 -> 指定文件中 audits_callback_error.json
            pass
