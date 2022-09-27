# -*- coding: utf-8 -*-
#
from django.utils.translation import ugettext as _

from common.utils import get_logger


logger = get_logger(__file__)
__all__ = [
    'check_asset_can_run_ansible', 'clean_ansible_task_hosts',
    'group_asset_by_platform', 'group_asset_by_auth_type', 'color_string'
]


def check_asset_can_run_ansible(asset):
    if not asset.is_active:
        msg = _("Asset has been disabled, skipped: {}").format(asset)
        logger.info(msg)
        return False
    if not asset.is_support_ansible():
        msg = _("Asset may not be support ansible, skipped: {}").format(asset)
        logger.info(msg)
        return False
    return True


def check_system_user_can_run_ansible(system_user):
    if not system_user.auto_push:
        logger.warn(f'Push system user task skip, auto push not enable: system_user={system_user.name}')
        return False
    if not system_user.is_protocol_support_push:
        logger.warn(f'Push system user task skip, protocol not support: '
                    f'system_user={system_user.name} protocol={system_user.protocol} '
                    f'support_protocol={system_user.SUPPORT_PUSH_PROTOCOLS}')
        return False

    # Push root as system user is dangerous
    if system_user.username.lower() in ["root", "administrator"]:
        msg = _("For security, do not push user {}".format(system_user.username))
        logger.info(msg)
        return False

    return True


def clean_ansible_task_hosts(assets, system_user=None):
    if system_user and not check_system_user_can_run_ansible(system_user):
        return []
    cleaned_assets = []
    for asset in assets:
        if not check_asset_can_run_ansible(asset):
            continue
        cleaned_assets.append(asset)
    if not cleaned_assets:
        logger.info(_("No assets matched, stop task"))
    return cleaned_assets


def group_asset_by_platform(asset):
    if asset.is_unixlike():
        return 'unixlike'
    elif asset.is_windows():
        return 'windows'
    else:
        return 'other'


def group_asset_by_auth_type(assets):
    custom_asset = []
    ansible_asset = []
    for asset in assets:
        if asset.is_bind_custom_command:
            custom_asset.append(asset)
        else:
            ansible_asset.append(asset)
    return custom_asset, ansible_asset


def color_string(string, color='green'):
    color_map = {
        'red': '31m',
        'green': '32m'
    }
    color_ = color_map.get(color, '32m')
    return u'\033[{}{}\033[0m'.format(color_, string)
