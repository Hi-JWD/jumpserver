from celery import shared_task
from django.utils.translation import gettext_lazy as _

from behemoth.libs.pools.worker import worker_pool


@shared_task(verbose_name=_('Worker run task'))
def run_task_sync(execution):
    try:
        worker_pool.work(execution)
    except Exception as e:
        worker_pool.refresh_task_info(execution, 'error', str(e))
