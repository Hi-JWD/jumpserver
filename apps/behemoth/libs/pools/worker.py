import base64
import json
import os

from typing import Dict, AnyStr

from django.utils.translation import gettext as _
from django.conf import settings
from django.core.cache import cache
from difflib import SequenceMatcher
from rest_framework.utils.encoders import JSONEncoder

from assets.models import Asset
from assets.const.database import DatabaseTypes
from behemoth import const
from behemoth.models import Worker, Execution
from behemoth.serializers import SimpleCommandSerializer
from behemoth.utils import colored_printer as p
from common.utils import get_logger, random_string
from common.exceptions import JMSException
from orgs.models import Organization
from ops.celery.utils import get_celery_task_log_path


logger = get_logger(__name__)


class AWorker(object):
    def __init__(self, id='', name='', org_id=''):
        self.id = id
        self.name = name
        self.org_id = str(org_id)

    @staticmethod
    def get_labels():
        return []


class WorkerPool(object):
    def __init__(self) -> None:
        self._org_id = Organization.DEFAULT_ID
        self._workers: Dict[AnyStr, Dict[AnyStr, Dict[AnyStr, Worker]]] = {}
        self._default_workers: Dict[AnyStr, Dict[AnyStr, Worker]] = {}
        # other
        self.worker_status_key = ':worker_status_key:'

    def select_org(self, org_id=None):
        if org_id is not None:
            self._org_id = str(org_id)
            for d in (self._workers, self._default_workers):
                d.setdefault(self._org_id, {})

    def __get_workers(self) -> list[Worker]:
        default_workers: Dict = self._default_workers.get(self._org_id, {})
        other_workers: Dict = self._workers.get(self._org_id, {})
        return list(other_workers.values()) + list(default_workers.values())

    def add_worker(self, worker: Worker) -> None:
        self.select_org(worker.org_id)
        labels = worker.get_labels()
        if labels:
            for label in labels:
                self._workers[str(worker.org_id)][label][worker.name] = worker
        else:
            self._default_workers[str(worker.org_id)][worker.name] = worker
        logger.debug(f'Add worker：{worker}({", ".join(labels) or _("No label")})')

    def delete_worker(self, worker: Worker | AWorker) -> None:
        self.select_org(worker.org_id)
        worker_set = set()
        labels = worker.get_labels()
        if labels:
            for label in labels:
                w = self._workers[str(worker.org_id)][label].pop(worker.name, None)
                worker_set.add(w)
        else:
            w = self._default_workers[str(worker.org_id)].pop(worker.name, None)
            worker_set.add(w)
        logger.debug(f'Delete worker：{worker_set}({", ".join(labels) or _("No label")})')

    def __select_worker(self, asset: Asset) -> Worker | None:
        worker: Worker | None = None
        if not (labels := asset.get_labels()):
            all_workers: list[Worker] = self.__get_workers()
            worker = all_workers.pop() if len(all_workers) > 0 else None
        else:
            # 根据标签选择工作机
            minimum_ratio, closest_label = 0, ''
            for label in self._workers[self._org_id].keys():
                ratio: float = SequenceMatcher(None, labels[0], label).ratio()
                if ratio <= minimum_ratio:
                    continue
                minimum_ratio, closest_label = ratio, label

            if workers := self._workers[self._org_id][closest_label]:
                __, worker = workers.popitem()

            default_workers = self._default_workers[self._org_id]
            if worker is None and default_workers:
                __, worker = default_workers.popitem()

        return worker

    def mark_worker_status(self, w: Worker) -> None:
        workers = cache.get(self.worker_status_key, [])
        workers.append({'id': w.id, 'name': w.name, 'org_id': w.org_id})
        cache.set(self.worker_status_key, workers, timeout=3600 * 24)

    def refresh_all_workers(self) -> None:
        workers = cache.get(self.worker_status_key, [])
        for worker in workers:
            self.delete_worker(AWorker(**worker))
            if worker := Worker.objects.filter(id=worker['id']):
                self.add_worker(worker)

    def __get_valid_worker(self, execution: Execution) -> str:
        while True:
            # 根据资产属性选择一个工作机
            worker: Worker | None = self.__select_worker(execution.asset)
            if not worker:
                raise JMSException(_('Not found a valid worker'))
            # 检查工作机是否可连接
            connectivity: bool = worker.test_connectivity(False)
            if not connectivity:
                print(p.yellow(_('Worker[%s] is not valid') % worker))
            else:
                self.add_worker(worker)
                break
        return worker.id

    @staticmethod
    def record(e: Execution, text: str, color='info'):
        formater = getattr(p, color, 'info')
        log_file = get_celery_task_log_path(e.task_id)
        with open(log_file, 'a') as f:
            f.write(formater(text))

    def __pre_run(self, execution: Execution) -> None:
        print(p.info('正在寻找有效的工作机...'))
        self.select_org(execution.org_id)
        self.refresh_all_workers()
        execution.worker_id = self.__get_valid_worker(execution)
        execution.save(update_fields=['worker_id'])

    @staticmethod
    def __generate_command_file(execution: Execution) -> str:
        # TODO 【命令缓存】命令生成后再缓存中保存一份，减少命令回调的数据查询
        # TODO 如果命令更新了，对应的execution下的命令缓存要及时刷新
        commands = execution.get_commands(get_all=False)
        print(p.info(f'共 {len(commands)} 条命令待执行'))
        data = {
            'command_set': SimpleCommandSerializer(commands, many=True).data,
        }
        filename: str = f'{execution.id}.bs'
        filepath = os.path.join(settings.BEHEMOTH_DIR, filename)
        with open(filepath, 'w') as f:
            f.write(json.dumps(data, cls=JSONEncoder))
        return filepath

    @staticmethod
    def __create_token(user_id: str) -> str:
        expiration = settings.TOKEN_EXPIRATION or 3600
        remote_addr = base64.b16encode('0.0.0.0'.encode('utf-8'))  # .replace(b'=', '')
        cache_key = '%s_%s' % (user_id, remote_addr)
        token = cache.get(cache_key)
        if not token:
            token = random_string(36)
        cache.set(token, user_id, expiration)
        cache.set('%s_%s' % (user_id, remote_addr), token, expiration)
        return token

    def __build_params(self, execution: Execution) -> dict:
        print(p.info('正在构建命令执行需要的参数信息'))
        command_filepath: str = f'{execution.id}.bs'
        local_cmds_file = self.__generate_command_file(execution)
        remote_cmds_file = f'/tmp/behemoth/commands/{command_filepath}'
        token = self.__create_token(execution.user_id)
        auth = {
            'address': execution.asset.address,
            'username': execution.account.username,
            'password': execution.account.password,
            'db_name': execution.asset.database.db_name
        }
        if execution.asset.type == DatabaseTypes.MYSQL:
            cmd_type = script = 'mysql'
            auth['port'] = execution.asset.get_protocol_port('mysql')
        elif execution.asset.type == DatabaseTypes.ORACLE:
            cmd_type = script = 'oracle'
            auth.update({
                'port': execution.asset.get_protocol_port('oracle'),
                'privileged': execution.account.privileged
            })
        else:
            cmd_type = script = 'script'
        params: dict = {
            'host': settings.SITE_URL, 'cmd_type': cmd_type, 'script': script,
            'auth': auth, 'token': str(token), 'task_id': str(execution.id),
            'encrypted_data': False, 'remote_commands_file': remote_cmds_file,
            'local_commands_file': local_cmds_file, 'org_id': str(execution.org_id),
            'envs': execution.worker.envs,
        }
        return params

    def __run(self, execution: Execution) -> None:
        run_params: dict = self.__build_params(execution)
        execution.worker.run(run_params)

    def work(self, execution: Execution) -> None:
        print(p.green('开始执行任务'))
        try:
            self.__pre_run(execution)
            self.__run(execution)
        except Exception as err:
            err_msg = f'针对 {execution.asset} 的任务执行失败: {err}'
            execution.status = const.TaskStatus.failed
            execution.reason = err_msg
            execution.save(update_fields=['status', 'reason'])
            print(p.red(err_msg))
        else:
            print(p.green('任务执行成功'))


worker_pool = WorkerPool()
