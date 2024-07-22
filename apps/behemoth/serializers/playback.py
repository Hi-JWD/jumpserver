from rest_framework import serializers
from django.utils.translation import gettext as _

from common.serializers.fields import ObjectRelatedField
from common.serializers import CommonModelSerializer
from ..models import Playback, Environment, PlaybackExecution


class PlaybackSerializer(serializers.ModelSerializer):
    environment = ObjectRelatedField(
        required=False, queryset=Environment.objects, allow_null=True,
        allow_empty=True, label=_('Environment')
    )

    class Meta:
        model = Playback
        fields_mini = ['id', 'name']
        fields_small = fields_mini + ['environment']
        fields = fields_small


class PlaybackTaskSerializer(serializers.Serializer):
    pass


class PlaybackExecutionSerializer(CommonModelSerializer):
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
    pause = serializers.BooleanField()
