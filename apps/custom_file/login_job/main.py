# data/login_job/main.py

import requests

from django.conf import settings


def get_job(user):
    options = []
    resp = requests.get(settings.SELECT_JOB_URL, params={"phone": user.phone})
    try:
        options = resp.json().get('orders', [])
    except Exception: # noqa
        pass
    return options
