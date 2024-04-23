from django.db import models
from django.utils.translation import gettext_lazy as _

from perms.const import ActionChoices
from assets.models import Asset
from accounts.const import AliasAccount
from .general import Ticket

__all__ = ['ApplyAssetTicket']

asset_or_node_help_text = _("Select at least one asset or node")


class ApplyAssetTicket(Ticket):
    apply_permission_name = models.CharField(max_length=128, verbose_name=_('Permission name'))
    apply_nodes = models.ManyToManyField('assets.Node', verbose_name=_('Node'))
    # 申请信息
    apply_assets = models.ManyToManyField('assets.Asset', verbose_name=_('Asset'))
    apply_accounts = models.JSONField(default=list, verbose_name=_('Apply accounts'))
    apply_actions = models.IntegerField(verbose_name=_('Actions'), default=ActionChoices.connect)
    apply_date_start = models.DateTimeField(verbose_name=_('Date start'), null=True)
    apply_date_expired = models.DateTimeField(verbose_name=_('Date expired'), null=True)

    @property
    def apply_accounts_display(self):
        result = []
        for item in self.apply_accounts:
            name = Asset.objects.filter(id=item['asset']).values_list('name').first()
            if name:
                input_f = AliasAccount.INPUT
                accounts = list(map(
                    lambda x: input_f.label if x == input_f.value else x, item['accounts']
                ))
                result.append({'asset': name[0], 'accounts': accounts})
        return result

    def get_apply_actions_display(self):
        return ActionChoices.display(self.apply_actions)

    class Meta:
        verbose_name = _('Apply Asset Ticket')
