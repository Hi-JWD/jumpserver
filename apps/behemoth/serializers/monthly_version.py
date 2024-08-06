from django.utils.translation import gettext as _
from rest_framework import serializers

from common.serializers.fields import ObjectRelatedField
from common.serializers import CommonModelSerializer
from ..models import MonthlyVersion, Playback


class PlaybackMonthlyVersionSerializer(CommonModelSerializer):
    playbacks = ObjectRelatedField(
        queryset=Playback.objects, many=True, required=False, label=_('Playback'),
    )
    action = serializers.CharField(write_only=True, required=True, label=_('Action'))

    class Meta:
        model = MonthlyVersion
        fields = ['playbacks', 'action']


class MonthlyVersionSerializer(CommonModelSerializer):
    playbacks = ObjectRelatedField(
        queryset=Playback.objects, many=True, required=False, label=_('Playback'),
    )

    class Meta:
        model = MonthlyVersion
        fields_mini = ['id', 'name']
        fields_small = fields_mini + ['date_created', 'created_by']
        fields = fields_small + ['playbacks', 'comment']
