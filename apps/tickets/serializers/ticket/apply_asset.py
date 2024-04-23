from django.utils.translation import gettext_lazy as _
from django.db import models

from perms.models import AssetPermission
from perms.serializers.permission import ActionChoicesField
from tickets.models import ApplyAssetTicket
from .common import BaseApplyAssetSerializer
from .ticket import TicketApplySerializer

__all__ = ['ApplyAssetSerializer', 'ApproveAssetSerializer']

asset_or_node_help_text = _("Select at least one asset or node")

apply_help_text = _('Support fuzzy search, and display up to 10 items')


class ApplyAssetSerializer(BaseApplyAssetSerializer, TicketApplySerializer):
    apply_actions = ActionChoicesField(required=False, allow_null=True, label=_("Apply actions"))
    permission_model = AssetPermission

    class Meta(TicketApplySerializer.Meta):
        model = ApplyAssetTicket
        writeable_fields = [
            'id', 'title', 'type', 'apply_actions', 'comment', 'org_id',
            'apply_date_start', 'apply_date_expired', 'apply_accounts',
        ]
        read_only_fields = (TicketApplySerializer.Meta.read_only_fields +
                            ['apply_permission_name', 'apply_accounts_display'])
        fields = TicketApplySerializer.Meta.fields_small + writeable_fields + read_only_fields
        ticket_extra_kwargs = TicketApplySerializer.Meta.extra_kwargs
        extra_kwargs = {
            'apply_date_start': {'allow_null': False},
            'apply_date_expired': {'allow_null': False},
            'apply_accounts': {'write_only': True},
        }
        extra_kwargs.update(ticket_extra_kwargs)

    def validate(self, attrs):
        attrs['type'] = 'apply_asset'
        attrs = super().validate(attrs)
        return attrs

    @classmethod
    def setup_eager_loading(cls, queryset):
        queryset = queryset.prefetch_related('apply_nodes', 'apply_assets')
        return queryset


class ApproveAssetSerializer(ApplyAssetSerializer):
    class Meta(ApplyAssetSerializer.Meta):
        read_only_fields = TicketApplySerializer.Meta.fields_small + \
                           ApplyAssetSerializer.Meta.read_only_fields
