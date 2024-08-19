from celery import shared_task
from django.utils.translation import gettext_lazy as _

from behemoth.libs.pools.worker import worker_pool
from behemoth.utils import colored_printer as p
from behemoth.models import Execution
from behemoth.const import PlanCategory, TaskStatus, ExecutionCategory
from behemoth.exceptions import PauseException
from common.exceptions import JMSException


@shared_task(verbose_name=_('Worker run command task'))
def run_task_sync(executions: list[Execution], users: list[str]):
    worker_pool.refresh_task_status(executions)
    total, can_continue, pre_task_id = len(executions), True, ''
    for num, execution in enumerate(executions, 1):
        if worker_pool.is_task_failed(pre_task_id):
            break

        if num == 1 and execution.category == ExecutionCategory.pause:
            execution.status = TaskStatus.success
            execution.save(update_fields=['status'])
            print(p.info('检测到第一条命令类型为暂停，认为已经执行过，跳过处理'))

        print(p.info(
            _('There are %s batches of tasks in total. The %sth task has started to execute.'
              ) % (total, num))
        )
        try:
            if execution.status != TaskStatus.success:
                execution.status = TaskStatus.executing
                execution.save(update_fields=['status'])

            if execution.plan.category == PlanCategory.sync:
                environment = execution.plan.environment
                if execution.asset_name and execution.account_username:
                    new_asset_name = execution.asset_name.replace('：', ':').split(':', 1)[-1]
                    asset = environment.assets.filter(name__endswith=new_asset_name).first()
                    if not asset:
                        raise JMSException('环境[%s]下未找到资产[%s]' % (environment, exexcution.asset_name))

                    account = asset.accounts.filter(username=execution.account_username).first()
                    if not account:
                        raise JMSException(
                            '环境[%s]下的资产[%s]未找到账号[%s]' % (
                                environment, execution.asset_name, execution.account_username
                            )
                        )
                    execution.asset = asset
                    execution.account = account
                    execution.save(update_fields=['asset', 'account'])

            worker_pool.work(execution, users)
            pre_task_id = execution.id
        except PauseException as e:
            can_continue = False
            execution.status = TaskStatus.pause
            execution.reason = str(e)
            execution.save(update_fields=['status', 'reason'])
            print(p.yellow(str(e)))
        except Exception as err:
            can_continue = False
            err_msg = _('%s\'s task execution failed: %s') % (execution.asset or _("Unknown"), err)
            execution.status = TaskStatus.failed
            execution.reason = err_msg
            execution.save(update_fields=['status', 'reason'])
            print(p.red(err_msg))

        if not can_continue:
            break

