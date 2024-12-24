from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from common.serializers.fields import EncryptedField


__all__ = [
    'OtherSettingSerializer', 'CloudSettingSerializer', 'CloudRegionsSerializer'
]


class OtherSettingSerializer(serializers.Serializer):
    PREFIX_TITLE = _('More...')

    PERM_SINGLE_ASSET_TO_UNGROUP_NODE = serializers.BooleanField(
        required=False, label=_("Perm ungroup node"),
        help_text=_("Perm single to ungroup node")
    )

    # 准备废弃
    # PERIOD_TASK_ENABLED = serializers.BooleanField(
    #     required=False, label=_("Enable period task")
    # )


class CloudSettingSerializer(serializers.Serializer):
    PREFIX_TITLE = _('Cloud setting')

    GLOBAL_HW_API_ENDPOINT = serializers.CharField(
        max_length=128, required=True, label=_('API Endpoint')
    )
    GLOBAL_HW_SC_USERNAME = serializers.CharField(
        max_length=128, required=True, label=f"SC {_('Username')}"
    )
    GLOBAL_HW_SC_PASSWORD = EncryptedField(
        max_length=4096, required=False, label=f"SC {_('Password')}"
    )
    GLOBAL_HW_SC_DOMAIN = serializers.CharField(
        max_length=128, required=True, label=f"SC {_('Tenant Name')}"
    )


class CloudRegionsSerializer(serializers.Serializer):
    regions = serializers.ListField(label=_('Regions'))
