from collections import Counter

from django.utils.translation import gettext_lazy as _
from django.db.models import F, Count, Case, When

from accounts.models import Account
from assets.models import Asset, Node
from orgs.utils import tmp_to_root_org
from perms.models import AssetPermission
from reports import const as c

from .common import BaseReport, register_report_template


ASSET_REPORT_DESCRIPTION = """
统计各个组织下的资产数量
统计各个组织下资产授权情况
"""


@register_report_template
class AssetReport(BaseReport):
    NAME = _('Asset basic data report')
    DESCRIPTION = ASSET_REPORT_DESCRIPTION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # summary 数据
        self.assets_count = 0
        self.asset_type_count = 0
        self.accounts_count = 0
        self.pri_account_count = 0
        self.common_account_count = 0

    @tmp_to_root_org()
    def _get_type_of_assets_data(self):
        assets = Asset.objects.annotate(
            platform_name=F('platform__name')
        ).values('id', 'platform_name')

        self.assets_count = len(assets)
        type_assets_info, asset_type_counter = [], Counter()
        for a in assets:
            asset_type_counter.update([a['platform_name']])

        type_assets_info.extend(
            [(name, count) for name, count in asset_type_counter.items()]
        )
        max_type_name, max_type_count = self.get_info_from_counter(asset_type_counter)
        self.asset_type_count = len(asset_type_counter.keys())
        return [
            {
                'type': c.TEXT,
                'data': _(
                    _('There are currently %s asset types, '
                      'and the largest asset type is %s(%s), as shown below: ')
                ) % (
                    self.asset_type_count, max_type_name, max_type_count
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('Asset type'), _('Assets amount')], *type_assets_info]
            },
        ]

    @tmp_to_root_org()
    def _get_node_of_assets_data(self):
        primary_nodes = [
            n for n in Node.objects.all().order_by('-assets_amount') if n.level == 2
        ]
        assets_node_info = []
        if len(primary_nodes) > 0:
            node = primary_nodes[0]
            max_node_name, assets_amount = node.full_value, node.assets_amount
        else:
            max_node_name, assets_amount = '', 0
        for node in primary_nodes:
            assets_node_info.append((
                node.full_value, node.assets_amount, node.org_name
            ))
        return [
            {
                'type': c.TEXT,
                'data': _('Currently, there are a total of %s primary nodes, '
                          'with the highest number of assets under node %s, '
                          'which is %s, as shown below:') % (
                    len(primary_nodes), max_node_name, assets_amount
                )
            },
            {
                'type': c.TABLE_PIE,
                'data': [[_('Node Path'), _('Assets amount'), _('Organization')], *assets_node_info]
            }
        ]

    @tmp_to_root_org()
    def _get_perm_to_user_of_assets_data(self):
        # 授权没缓存，遍历查询会给数据库极大压力，手动计算吧
        # 构造一个map -> {asset: {user_id1, user_id2}}
        relation_map = {}
        permissions = AssetPermission.objects.valid().all()
        for p in permissions:
            user_ids = [u.id for u in p.get_all_users()]
            for a in p.get_all_assets():
                if user_set := relation_map.get(a):
                    user_set.update(user_ids)
                else:
                    user_set = set(user_ids)
                relation_map[a] = user_set

        assets_perm_info, max_perm = [], {'name': '', 'count': 0}
        for asset, user_ids in relation_map.items():
            user_amount = len(user_ids)
            assets_perm_info.append((
                asset.name, user_amount, asset.org_name
            ))
            if user_amount > max_perm['count']:
                max_perm = {
                    'name': asset.name, 'count': user_amount
                }
        return [
            {
                'type': c.TEXT,
                'data': _('The asset with the highest number of authorized users is %s, '
                          'and the authorized users are %s, as shown below:') % (
                    max_perm['name'], max_perm['count']
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [
                    [_('Asset display'), _('Authorized personnel'), _('Organization')],
                    *assets_perm_info
                ]
            }
        ]

    def _get_other_data(self):
        accounts = Account.objects.aggregate(
            privilege=Count(Case(When(privileged=True, then=1))),
            common=Count(Case(When(privileged=False, then=1)))
        )
        self.pri_account_count = accounts['privilege']
        self.common_account_count = accounts['common']
        self.accounts_count = self.pri_account_count + self.common_account_count

    def get_pdf_data(self):
        return [
            {
                'title': _('Number of assets by type'),
                'data': self._get_type_of_assets_data()
            },
            {
                'title': _('Number of assets on each node'),
                'data': self._get_node_of_assets_data()
            },
            {
                'title': _('Authorized Users by Asset (Top 10)'),
                'data': self._get_perm_to_user_of_assets_data()
            },
        ]

    def get_summary(self):
        self._get_other_data()
        return _('Currently, there are %s assets, %s types, '
                 'and %s accounts, including %s privileged accounts '
                 'and %s regular accounts.') % (
            self.assets_count, self.asset_type_count,
            self.accounts_count, self.pri_account_count,
            self.common_account_count
        )

