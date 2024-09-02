# -*- coding: utf-8 -*-
#
import uuid

from celery import current_task
from django.db import models
from django.utils.translation import gettext_lazy as _

from ops.mixin import PeriodTaskModelMixin
from common.db.models import JMSBaseModel
from common.const.choices import Trigger
from common.utils.timezone import local_now
from common.utils import get_logger
from reports.handler import ReportFileHandler


logger = get_logger(__file__)


class ReportFileType(models.TextChoices):
    pdf = 'pdf', _('PDF')


class Report(PeriodTaskModelMixin, JMSBaseModel):
    name = models.CharField(max_length=128, verbose_name=_('Name'))
    category = models.JSONField(default=list, verbose_name=_('Category'))
    file_type = models.CharField(
        max_length=32, default=ReportFileType.pdf, choices=ReportFileType.choices,
        verbose_name=_('Report file type')
    )
    recipients = models.ManyToManyField(
        'users.User', blank=True, verbose_name=_("Recipient")
    )
    statistical_cycle = models.JSONField(default=dict, verbose_name=_('Statistical cycle'))
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))

    def get_register_task(self):
        from reports.tasks import execute_report_task
        name = "report_period_{}".format(str(self.id)[:8])
        task = execute_report_task.name
        args = (str(self.id), Trigger.timing)
        kwargs = {}
        return name, task, args, kwargs

    def execute(self, trigger):
        try:
            cid = current_task.request.id
        except AttributeError:
            cid = str(uuid.uuid4())
        execution = ReportExecution.objects.create(
            id=cid, report=self, trigger=trigger
        )
        execution.start()
        return execution


class TaskStatus(models.TextChoices):
    running = 'running', _('Running')
    success = 'success', _('Success')
    failed = 'failed', _('Failed')


class ReportExecution(JMSBaseModel):
    trigger = models.CharField(
        max_length=128, default=Trigger.manual, choices=Trigger.choices,
        verbose_name=_('Trigger mode')
    )
    status = models.CharField(
        max_length=16, default=TaskStatus.running,
        choices=TaskStatus.choices, verbose_name=_('Status'),
    )
    report = models.ForeignKey(
        Report, on_delete=models.CASCADE, related_name='executions',
        null=True, verbose_name=_('Result'),
    )
    result = models.JSONField(blank=True, null=True, verbose_name=_('Result'))
    date_finished = models.DateTimeField(null=True, verbose_name=_("Date finished"))

    class Meta:
        ordering = ('-date_created',)

    @property
    def report_type(self):
        return '_'.join(self.report.category)

    def start(self):
        try:
            filepath = ReportFileHandler(self).run()
            self.status = TaskStatus.success
            self.result = {'filepath': filepath}
        except Exception as error:
            import traceback
            logger.error(f'Report generate failed: {traceback.format_exc()}')
            self.status = TaskStatus.failed
            self.result = {'message': str(error)}
        finally:
            self.date_finished = local_now()
            self.save()
