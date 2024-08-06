from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


class SyncPlanSerializer(serializers.Serializer):
    SYNC_PLAN_REQUIRED_PARTICIPANTS = serializers.IntegerField(
        min_value=2, max_value=10, default=2, label=_('Sync task participants')
    )
    SYNC_PLAN_WAIT_PARTICIPANT_IDLE = serializers.IntegerField(
        min_value=60, max_value=3600*24*365, default=3600, label=_('Sync task wait participant idle')
    )


class DeployPlanSerializer(serializers.Serializer):
    DEPLOY_PLAN_CUSTOM_TYPE = serializers.JSONField(
        default=list, label=_('Deploy task custom type')
    )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        has_default = filter(lambda x: x['id'] == 'default', data['DEPLOY_PLAN_CUSTOM_TYPE'])
        if not bool(list(has_default)):
            default = {'id': 'default', 'label': _('Default')}
            data['DEPLOY_PLAN_CUSTOM_TYPE'].insert(0, default)
        return data
