from rest_framework import serializers
from django.utils.translation import gettext as _

from common.serializers.fields import ObjectRelatedField
from ..models import Playback, Environment


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
