# ~*~ coding: utf-8 ~*~
from itertools import groupby

from celery import shared_task
from django.utils.translation import gettext_noop, gettext_lazy as _
from django.conf import settings

from assets.models import Asset
from assets.const import AutomationTypes, Connectivity
from assets.notifications import UnableConnectAssetUserMsg
from common.utils import get_logger
from users.models import User
from ops.celery.decorator import register_as_period_task
from orgs.utils import tmp_to_org, current_org, tmp_to_root_org
from orgs.models import Organization
from .common import quickstart_automation

logger = get_logger(__file__)

__all__ = [
    'test_assets_connectivity_task',
    'test_assets_connectivity_manual',
    'test_node_assets_connectivity_manual',
]


@shared_task(
    verbose_name=_('Test assets connectivity'), queue='ansible',
    activity_callback=lambda self, asset_ids, org_id, *args, **kwargs: (asset_ids, org_id)
)
def test_assets_connectivity_task(asset_ids, org_id, task_name=None):
    from assets.models import PingAutomation
    if task_name is None:
        task_name = gettext_noop("Test assets connectivity")

    task_name = PingAutomation.generate_unique_name(task_name)
    task_snapshot = {'assets': asset_ids}
    with tmp_to_org(org_id):
        quickstart_automation(task_name, AutomationTypes.ping, task_snapshot)


def test_assets_connectivity_manual(assets):
    task_name = gettext_noop("Test assets connectivity ")
    asset_ids = [str(i.id) for i in assets]
    org_id = str(current_org.id)
    return test_assets_connectivity_task.delay(asset_ids, org_id, task_name)


def test_node_assets_connectivity_manual(node):
    task_name = gettext_noop("Test if the assets under the node are connectable ")
    asset_ids = node.get_all_asset_ids()
    asset_ids = [str(i) for i in asset_ids]
    org_id = str(current_org.id)
    return test_assets_connectivity_task.delay(asset_ids, org_id, task_name)


@shared_task(verbose_name=_('Check unconnected assets'))
@register_as_period_task(interval=settings.ASSET_CHECK_PERIODIC)
@tmp_to_root_org()
def check_asset_permission_expired():
    """ 定期将资产异常的信息发送邮件给管理员 """
    def set_attr(obj, attr, value):
        obj[attr] = value
        return obj

    logger.info(f'Check unconnected assets.')
    assets = list(Asset.objects.values('org_id', 'id', 'address', 'name'))
    assets.sort(key=lambda x: x['org_id'])
    org_map = {
        str(o.id): o for o in Organization.objects.filter(
            id__in=[a['org_id'] for a in assets]
        )
    }
    reminder_assets = {}
    for org_id, org_asset in groupby(assets, lambda a: a['org_id']):
        org = org_map[org_id]
        asset_ids = [a['id'] for a in org_asset]
        test_assets_connectivity_task(asset_ids, org.id)
        with tmp_to_org(org):
            asset_objs = Asset.objects.filter(
                connectivity__in=[Connectivity.ERR, Connectivity.UNKNOWN]
            ).values('name', 'address', 'connectivity')
            assets = [
                set_attr(a, 'connectivity', Connectivity.get_label(a['connectivity'])) for a in asset_objs
            ]
            reminder_assets[org.name] = assets

    for user in User.get_super_admins():
        UnableConnectAssetUserMsg(user, reminder_assets).publish()
    logger.info(f'Check unconnected assets task finished.')
