# -*- coding: utf-8 -*-
#
from celery import shared_task
from django.utils.translation import gettext_lazy as _

from common.utils import get_object_or_none, get_logger
from orgs.utils import tmp_to_root_org

logger = get_logger(__file__)


@shared_task(verbose_name=_('Execute report task'))
def execute_report_task(rid, trigger):
    with tmp_to_root_org():
        from reports.models import Report
        report = get_object_or_none(Report, pk=rid)
        if not report:
            logger.error("No report found: {}".format(rid))
            return

        execute = report.execute(trigger)
    return execute
