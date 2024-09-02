from django.utils.dateparse import parse_datetime
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
            'file_type', 'date_created', 'created_by', 'statistical_cycle',
            'is_periodic', 'crontab', 'interval', 'comment', 'is_active'
        ]
        extra_kwargs = {
            'category': {'required': True},
            'statistical_cycle': {'required': True}
        }

    @staticmethod
    def get_category_display(obj):
        return get_report_templates(obj.category, get_name=True).values()

    @staticmethod
    def _valid_time(time_string):
        return parse_datetime(time_string) is not None

    def validate_statistical_cycle(self, statistical_cycle):
        period = statistical_cycle.get('period', '')
        if period and not str(period).isdigit():
            raise serializers.ValidationError(_('Period must be an integer'))
        start, end = statistical_cycle.get('dateStart', ''), statistical_cycle.get('dateEnd', '')
        if start and end and (not self._valid_time(start) or not self._valid_time(end)):
            raise serializers.ValidationError(_('The date format must be ISO format'))

        if not period and not (start and end):
            raise serializers.ValidationError(_('Period and date must be set one'))
        return statistical_cycle


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
