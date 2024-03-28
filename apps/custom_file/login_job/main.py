# data/login_job/main.py

import requests


get_job_url = "http://127.0.0.1/p/webapi/request/xxx/getOpreateorders?phone={}"


def get_job(user):
    options = []
    resp = requests.get(get_job_url.format(user.phone))
    try:
        options = resp.json().get('opreteOrders', [])
    except Exception: # noqa
        pass
    return options
