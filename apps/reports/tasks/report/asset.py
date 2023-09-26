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
    NAME = '资产基础数据报表'
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
                    '当前共有 %s 种资产类型，资产最多的类型为 %s(%s 个)，如下所示：'
                ) % (
                    self.asset_type_count, max_type_name, max_type_count
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('资产类型'), _('资产数量')], *type_assets_info]
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
                'data': _('当前共有一级节点 %s 个，其中节点 %s 下资产数最多，为 %s 台，如下所示：') % (
                    len(primary_nodes), max_node_name, assets_amount
                )
            },
            {
                'type': c.TABLE_PIE,
                'data': [[_('节点路径'), _('资产数'), _('组织')], *assets_node_info]
            }
        ]

    @tmp_to_root_org()
    def _get_perm_to_user_of_assets_data(self):
        # 授权没缓存，遍历查询会给数据库极大压力，手动计算吧
        # 构造一个map -> {asset: {user_id1, user_id2}}
        relation_map = {}
        permissions = AssetPermission.objects.valid().all()
        for p in permissions:
            user_ids = p.get_all_users(flat=True)
            for a in p.get_all_assets():
                if user_set:= relation_map.get(a):
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
                'data': _('被授权给用户数量最多的资产为 %s，授权用户为 %s 人，如下所示：') % (
                    max_perm['name'], max_perm['count']
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('资产名称'), _('授权人数'), _('组织')], *assets_perm_info]
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
                'title': '各类型资产数',
                'data': self._get_type_of_assets_data()
            },
            {
                'title': '各节点资产数',
                'data': self._get_node_of_assets_data()
            },
            {
                'title': '各资产授权用户 (Top 10)',
                'data': self._get_perm_to_user_of_assets_data()
            },
        ]

    def get_summary(self):
        self._get_other_data()
        return '''
        当前共有资产 %s 个，共 %s 种类型资产，
        账号共 %s 个，其中特权账号 %s 个，普通账号 %s 个。
        ''' % (
            self.assets_count, self.asset_type_count,
            self.accounts_count, self.pri_account_count,
            self.common_account_count
        )

