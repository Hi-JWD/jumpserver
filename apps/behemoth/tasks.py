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
    if len(executions) == 0:
        print(p.yellow(_('No task to run')))
        return

    worker_pool.refresh_task_status(executions)
    print(p.cyan('本任务执行人为: %s' % ', '.join(users)))
    total, can_continue, pre_task_id = len(executions), True, ''
    for num, execution in enumerate(executions, 1):
        if worker_pool.is_task_failed(pre_task_id):
            break

        print(p.info('共 %s 批任务，开始执行第 %s 个任务' % (total, num)))
        try:
            execution.status = TaskStatus.executing
            execution.save(update_fields=['status'])

            if execution.plan.category == PlanCategory.sync:
                environment = execution.plan.environment
                if execution.asset_name and execution.account_username:
                    asset = environment.assets.filter(name__endswith=execution.asset_name).first()
                    if not asset:
                        raise JMSException('环境[%s]下未找到资产[%s]' % (environment, execution.asset_name))

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
                print(p.cyan('同步计划前置条件准备成功'))
            worker_pool.work(execution)
            pre_task_id = execution.id
        except PauseException as e:
            can_continue = False
            execution.status = TaskStatus.pause
            execution.reason = str(e)
            execution.save(update_fields=['status', 'reason'])
            print(p.yellow(str(e)))
        except Exception as err:
            can_continue = False
            err_msg = f'{execution.asset or _("Unknown")} 的任务执行失败: {err}'
            execution.status = TaskStatus.failed
            execution.reason = err_msg
            execution.save(update_fields=['status', 'reason'])
            print(p.red(err_msg))

        if not can_continue:
            break

