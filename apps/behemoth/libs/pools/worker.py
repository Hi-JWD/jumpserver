import os

import json
import redis

from functools import partial
from typing import Dict, AnyStr, Any, List

from django.utils.translation import gettext as _
from django.conf import settings
from django.core.cache import cache
from difflib import SequenceMatcher
from rest_framework.utils.encoders import JSONEncoder
from redis import Redis

from assets.models import Asset
from assets.const.database import DatabaseTypes
from behemoth import const
from behemoth.models import Worker, Execution
from behemoth.serializers import SimpleCommandSerializer
from common.utils import get_logger
from common.exceptions import JMSException
from orgs.models import Organization


logger = get_logger(__name__)


class WorkerPool(object):
    def __init__(self) -> None:
        self._org_id = Organization.DEFAULT_ID
        self._workers: Dict[AnyStr, Dict[AnyStr, Dict[AnyStr, Worker]]] = {}
        self._default_workers: Dict[AnyStr, Dict[AnyStr, Worker]] = {}
        self._running_workers: Dict[AnyStr, Dict[AnyStr, Worker]] = {}
        self._useless_workers: Dict[AnyStr, Dict[AnyStr, Worker]] = {}
        # other
        self._client: Redis | None = None

    def get_cache(self):
        if self._client is None or not self._client.ping():
            self._client = cache.client.get_client()
        return self._client

    def select_org(self, org_id=None):
        if org_id is not None:
            self._org_id = org_id
            for d in (
                    self._workers, self._default_workers,
                    self._running_workers, self._useless_workers
            ):
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
                self._workers[worker.org_id][label][worker.name] = worker
        else:
            self._default_workers[worker.org_id][worker.name] = worker
        logger.debug(f'Add worker：{worker}({", ".join(labels) or _("No label")})')

    def delete_worker(self, worker: Worker) -> None:
        self.select_org(worker.org_id)
        labels = worker.get_labels()
        if labels:
            for label in labels:
                self._workers[worker.org_id][label].pop(worker.name, None)
        else:
            self._default_workers[worker.org_id].pop(worker.name, None)
        logger.debug(f'Delete worker：{worker}({", ".join(labels) or _("No label")})')

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

    def __get_valid_worker(self, execution: Execution) -> Worker:
        while True:
            # 根据资产属性选择一个工作机
            worker: Worker | None = self.__select_worker(execution.asset)
            if not worker:
                raise JMSException(_('Not found a valid worker'))
            # 检查工作机是否可连接
            connectivity: bool = worker.test_connectivity(False)
            if not connectivity:
                self._useless_workers[self._org_id][str(worker.id)] = worker
                raise JMSException(_('Worker[%s] is not valid') % worker)
            else:
                self.add_worker(worker)
                self._running_workers[self._org_id][str(execution.id)] = worker
                break
        return worker

    def _pop_commands_from_cache(self, key) -> List:
        with self.get_cache().pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    commands = pipe.lrange(key, 0, -1)
                    if not commands:
                        pipe.unwatch()
                        return commands

                    pipe.multi()
                    pipe.delete(key)
                    pipe.execute()
                    commands = [json.loads(c) for c in commands]
                    return commands
                except redis.WatchError:
                    continue

    def refresh_task_info(self, e: Execution, type_: AnyStr, value: Any, ttl: int = 3600 * 4):
        client = self.get_cache()
        cache.set(const.TASK_TYPE_CACHE_KEY.format(e.id), type_, ttl)
        if type_ == 'command_cb':
            client.expire(const.TASK_DATA_CACHE_KEY.format(e.id), ttl)
            client.rpush(const.TASK_DATA_CACHE_KEY.format(e.id), json.dumps(value))
        else:
            cache.set(const.TASK_DATA_CACHE_KEY.format(e.id), value, ttl)

    def get_task_info(self, e: Execution) -> Dict:
        type_ = cache.get(const.TASK_TYPE_CACHE_KEY.format(e.id))
        if type_ == 'command_cb':
            data = self._pop_commands_from_cache(const.TASK_DATA_CACHE_KEY.format(e.id))
        else:
            data = cache.get(const.TASK_DATA_CACHE_KEY.format(e.id), {})
        return {'type': type_, 'data': data}

    def __pre_run(self, execution: Execution) -> None:
        self.refresh_task_info(execution, 'show_tip',  '正在获取一个有效的工作机')
        self.select_org(execution.org_id)
        execution.worker = self.__get_valid_worker(execution)
        execution.save(update_fields=['worker'])

    @staticmethod
    def __generate_command_file(execution: Execution) -> str:
        # TODO 【命令缓存】命令生成后再缓存中保存一份，减少命令回调的数据查询
        commands = execution.get_commands(get_all=False)
        data = {
            'command_set': SimpleCommandSerializer(commands, many=True).data,
        }
        filename: str = f'{execution.id}.bs'
        filepath = os.path.join(settings.COMMAND_DIR, filename)
        with open(filepath, 'w') as f:
            f.write(json.dumps(data, cls=JSONEncoder))
        return filepath

    def __build_params(self, execution: Execution) -> dict:
        self.refresh_task_info(execution, 'show_tip', '正在构建命令执行需要的参数信息')
        command_filepath: str = f'{execution.id}.bs'
        local_cmds_file = self.__generate_command_file(execution)
        remote_cmds_file = f'/tmp/behemoth/commands/{command_filepath}'
        token, __ = execution.user.create_bearer_token()
        if execution.asset.type == DatabaseTypes.MYSQL:
            cmd_type = script = 'mysql'
            auth = {
                'address': execution.asset.address,
                'port': execution.asset.get_protocol_port('mysql'),
                'username': execution.account.username,
                'password': execution.account.password,
                'db_name': execution.asset.database.db_name
            }
        else:
            cmd_type = script = 'script'
            auth = {}
        params: dict = {
            'host': settings.SITE_URL, 'cmd_type': cmd_type, 'script': script,
            'auth': auth, 'token': str(token), 'task_id': str(execution.id),
            'encrypted_data': False, 'remote_commands_file': remote_cmds_file,
            'local_commands_file': local_cmds_file, 'org_id': str(execution.org_id)
        }
        return params

    def __run(self, execution: Execution) -> None:
        run_params: dict = self.__build_params(execution)
        cb = partial(self.refresh_task_info, e=execution)
        execution.worker.run(run_params, callback=cb)

    def work(self, execution: Execution) -> None:
        err_msg = ''
        try:
            self.__pre_run(execution)
            self.__run(execution)
        except Exception as err:
            err_msg = f'{execution.asset} work failed: {err}'
            logger.error(err_msg)
            worker_pool.refresh_task_info(execution, 'error', str(err_msg))
        finally:
            self.done(execution, err_msg)

    @staticmethod
    def done(execution: Execution, err_msg: AnyStr) -> None:
        execution.status = const.TaskStatus.failed if err_msg else const.TaskStatus.executing
        execution.reason = err_msg
        execution.save(update_fields=['status', 'reason'])

    def check(self):
        # TODO 定时检测 self._useless_workers 中的 Worker 活性
        pass


worker_pool = WorkerPool()
