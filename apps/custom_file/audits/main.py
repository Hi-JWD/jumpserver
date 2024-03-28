# data/audits/main.py

import requests

from users.utils import JobUtil
from common.utils import get_logger


logger = get_logger(__name__)

callback_url = 'http://127.0.0.1/callback/'


def audit_callback(category, data):
    if category == 'host_session_log':
        try:
            data['job_id'] = JobUtil(data['user_id']).get_job()
            requests.post(callback_url, json=data)
        except Exception as e:
            logger.error('Audit callback error: {}'.format(e))
