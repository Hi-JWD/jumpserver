from typing import List

from django.db.models import Q

from common.utils.common import timeit
from assets.models import Node, Asset, AuthBook
from assets.pagination import NodeAssetTreePagination
from common.utils import lazyproperty
from assets.utils import get_node, is_query_node_all_assets


class SerializeToTreeNodeMixin:

    @timeit
    def serialize_nodes(self, nodes: List[Node], with_asset_amount=False):
        if with_asset_amount:
            def _name(node: Node):
                auth_book_qs = AuthBook.objects.all()
                asset_amount = node.assets_amount
                username = self.request.query_params.get('username')
                allow_change_auth = self.request.query_params.get('allow_change_auth')
                if allow_change_auth == '1':
                    auth_book_qs = auth_book_qs.filter(allow_change_auth=True)
                if username:
                    # 这里要优化一下，不能每次查询都走数据库
                    node_assets = node.get_all_assets()
                    asset_list = auth_book_qs.filter(
                        Q(systemuser__username=username) | Q(username=username)
                    ).values_list('asset_id', flat=True)
                    if asset_list:
                        asset_amount = node_assets.filter(id__in=asset_list).count()
                return '{} ({})'.format(node.value, asset_amount)
        else:
            def _name(node: Node):
                return node.value
        data = [
            {
                'id': node.key,
                'name': _name(node),
                'title': _name(node),
                'pId': node.parent_key,
                'isParent': True,
                'open': True,
                'meta': {
                    'data': {
                        "id": node.id,
                        "key": node.key,
                        "value": node.value,
                    },
                    'type': 'node'
                }
            }
            for node in nodes
        ]
        return data

    def get_platform(self, asset: Asset):
        default = 'file'
        icon = {'windows', 'linux'}
        platform = asset.platform_base.lower()
        if platform in icon:
            return platform
        return default

    @timeit
    def serialize_assets(self, assets, node_key=None):
        if node_key is None:
            get_pid = lambda asset: getattr(asset, 'parent_key', '')
        else:
            get_pid = lambda asset: node_key

        data = [
            {
                'id': str(asset.id),
                'name': asset.hostname,
                'title': asset.ip,
                'pId': get_pid(asset),
                'isParent': False,
                'open': False,
                'iconSkin': self.get_platform(asset),
                'chkDisabled': not asset.is_active,
                'meta': {
                    'type': 'asset',
                    'data': {
                        'id': asset.id,
                        'hostname': asset.hostname,
                        'ip': asset.ip,
                        'protocols': asset.protocols_as_list,
                        'platform': asset.platform_base,
                        'org_name': asset.org_name
                    },
                }
            }
            for asset in assets
        ]
        return data


class FilterAssetByNodeMixin:
    pagination_class = NodeAssetTreePagination

    @lazyproperty
    def is_query_node_all_assets(self):
        return is_query_node_all_assets(self.request)

    @lazyproperty
    def node(self):
        return get_node(self.request)
