from django.utils.translation import gettext_lazy as _
from django.core.files.storage import default_storage
from rest_framework import serializers

from common.const.choices import Trigger
from common.serializers.fields import LabeledChoiceField
from ops.mixin import PeriodTaskSerializerMixin
from reports.models import Report, ReportExecution
from reports.tasks.report.common import get_report_templates


class ReportSerializer(PeriodTaskSerializerMixin, serializers.ModelSerializer):
    category_display = serializers.SerializerMethodField(label=_('Category'))

    class Meta:
        model = Report
        fields = [
            'id', 'name', 'category', 'category_display',
            'file_type', 'date_created', 'created_by',
            'is_periodic', 'crontab', 'interval', 'comment', 'period', 'is_active'
        ]

    @staticmethod
    def get_category_display(obj):
        return get_report_templates(obj.category, get_name=True).values()

    @staticmethod
    def validate_category(category):
        return category


class ReportExecutionSerializer(serializers.ModelSerializer):
    trigger = LabeledChoiceField(
        choices=Trigger.choices, label=_("Trigger mode"), read_only=True
    )
    can_download = serializers.SerializerMethodField()

    class Meta:
        model = ReportExecution
        read_only_fields = [
            'id', 'date_created', 'date_finished', 'created_by',
            'trigger', 'result', 'status', 'can_download'
        ]
        fields = read_only_fields + ['report']

    @staticmethod
    def get_can_download(obj):
        can = False
        result = getattr(obj, 'result', {}) or {}
        if path := result.get('filepath'):
            can = default_storage.exists(path)
        return can
