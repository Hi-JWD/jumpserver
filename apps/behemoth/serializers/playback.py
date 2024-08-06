from rest_framework import serializers
from django.utils.translation import gettext as _

from common.serializers.fields import ObjectRelatedField
from common.serializers import CommonModelSerializer
from ..models import Playback, MonthlyVersion, PlaybackExecution, Execution


class SimplePlaybackSerializer(CommonModelSerializer):
    class Meta:
        model = Playback
        fields = ['id', 'name', 'created_by', 'date_created', 'comment']


class PlaybackSerializer(CommonModelSerializer):
    monthly_version = ObjectRelatedField(
        required=True, queryset=MonthlyVersion.objects, label=_('Monthly version')
    )

    class Meta:
        model = Playback
        fields_mini = ['id', 'name']
        fields_small = fields_mini + ['created_by', 'date_created']
        fields = fields_small + ['monthly_version', 'comment']


class PlaybackTaskSerializer(serializers.Serializer):
    pass


class PlaybackExecutionSerializer(CommonModelSerializer):
    execution = ObjectRelatedField(
        queryset=Execution.objects, allow_null=True, allow_empty=True,
        attrs=('id', 'name', 'version', 'category'), label=_('Execution')
    )

    class Meta:
        model = PlaybackExecution
        fields_mini = ['id', 'plan_name']
        fields_small = fields_mini + [
            'date_created', 'created_by',
        ]
        fields = fields_small + ['playback', 'execution']


class InsertPauseSerializer(serializers.Serializer):
    input = serializers.CharField()
    output = serializers.CharField()
