# ~*~ coding: utf-8 ~*~

from celery import shared_task
from django.utils.translation import ugettext as _, gettext_noop

from common.utils import get_logger
from orgs.utils import org_aware_func
from ..models import Connectivity
from . import const
from .utils import check_asset_can_run_ansible
from . import test_asset_connectivity_by_ssh


logger = get_logger(__file__)


__all__ = [
    'test_account_connectivity_by_ansible', 'test_accounts_connectivity_manual',
    'get_test_account_connectivity_tasks', 'test_user_connectivity',
    'run_adhoc',
]


def get_test_account_connectivity_tasks(asset):
    if asset.is_unixlike():
        tasks = const.PING_UNIXLIKE_TASKS
    elif asset.is_windows():
        tasks = const.PING_WINDOWS_TASKS
    else:
        msg = _(
            "The asset {} system platform {} does not "
            "support run Ansible tasks".format(asset.hostname, asset.platform)
        )
        logger.info(msg)
        tasks = []
    return tasks


def run_adhoc(task_name, tasks, inventory):
    """
    :param task_name
    :param tasks
    :param inventory
    """
    from ops.ansible.runner import AdHocRunner
    runner = AdHocRunner(inventory, options=const.TASK_OPTIONS)
    result = runner.run(tasks, 'all', task_name)
    return result.results_raw, result.results_summary


def test_user_connectivity(task_name, asset, username, password=None, private_key=None):
    """
    :param task_name
    :param asset
    :param username
    :param password
    :param private_key
    """
    from ops.inventory import JMSCustomInventory

    tasks = get_test_account_connectivity_tasks(asset)
    if not tasks:
        logger.debug("No tasks ")
        return {}, {}
    inventory = JMSCustomInventory(
        assets=[asset], username=username, password=password,
        private_key=private_key
    )
    raw, summary = run_adhoc(
        task_name=task_name, tasks=tasks, inventory=inventory
    )
    return raw, summary


@org_aware_func("account")
def test_account_connectivity_by_ansible(account, task_name):
    """
    :param account: <AuthBook>对象
    :param task_name:
    :return:
    """
    if not check_asset_can_run_ansible(account.asset):
        return

    account.load_auth()
    try:
        raw, summary = test_user_connectivity(
            task_name=task_name, asset=account.asset,
            username=account.username, password=account.password,
            private_key=account.private_key_file
        )
    except Exception as e:
        logger.warn("Failed run adhoc {}, {}".format(task_name, e))
        return

    if summary.get('success'):
        account.set_connectivity(Connectivity.ok)
    else:
        account.set_connectivity(Connectivity.failed)


@org_aware_func("account")
def test_account_connectivity_by_ssh(account, task_name):
    account.load_auth()
    summary = test_asset_connectivity_by_ssh(
        [account.asset], username=account.username, password=account.password
    )

    if summary.get('success'):
        account.set_connectivity(Connectivity.ok)
    else:
        account.set_connectivity(Connectivity.failed)


@shared_task(queue="ansible")
def test_accounts_connectivity_manual(accounts):
    """
    :param accounts: <AuthBook>对象
    """
    for account in accounts:
        task_name = gettext_noop("Test account connectivity: ") + str(account)
        if account.asset.is_bind_custom_command:
            test_account_connectivity_by_ssh(account, task_name)
        else:
            test_account_connectivity_by_ansible(account, task_name)
        print(".\n")
