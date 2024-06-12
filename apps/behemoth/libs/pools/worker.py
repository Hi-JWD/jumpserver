import os

import json

from typing import Dict, AnyStr, Callable

from django.utils.translation import gettext as _
from django.conf import settings
from difflib import SequenceMatcher
from rest_framework.utils.encoders import JSONEncoder

from assets.models import Asset
from assets.const.database import DatabaseTypes
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
        self._running_cbs: Dict[AnyStr, Callable] = {}

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
        logger.debug(f'Add worker：{worker}({", ".join(labels) or _("No label")})')
        if labels:
            for label in labels:
                self._workers[worker.org_id][label][worker.name] = worker
        else:
            self._default_workers[worker.org_id][worker.name] = worker

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

    def __get_valid_worker(self, execution: Execution, callback: Callable) -> Worker:
        while True:
            # 根据资产属性选择一个工作机
            worker: Worker | None = self.__select_worker(execution.asset)
            if not worker:
                raise JMSException(_('Not found a valid worker'))
            # 检查工作机是否可连接
            connectivity: bool = worker.test_connectivity(False)
            if not connectivity:
                callback('工作机不可连接，请重试')
                self._useless_workers[self._org_id][str(worker.id)] = worker
            else:
                self.add_worker(worker)
                self._running_workers[self._org_id][str(execution.id)] = worker
                break
        return worker

    def __pre_run(self, execution: Execution, callback: Callable) -> None:
        callback('正在获取一个有效的工作机')
        self.select_org(execution.org_id)
        execution.worker = self.__get_valid_worker(execution, callback=callback)
        execution.save(update_fields=['worker'])

    @staticmethod
    def __generate_command_file(execution: Execution) -> str:
        commands = execution.get_commands()
        data = {
            'command_set': SimpleCommandSerializer(commands, many=True).data,
        }
        filename: str = f'{execution.id}.bs'
        filepath = os.path.join(settings.COMMAND_DIR, filename)
        with open(filepath, 'w') as f:
            f.write(json.dumps(data, cls=JSONEncoder))
        return filepath

    def __build_params(self, execution: Execution, callback: Callable) -> dict:
        callback('正在构建命令执行需要的参数信息')
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

    def __run(self, execution: Execution, callback: Callable) -> None:
        run_params: dict = self.__build_params(execution, callback)
        execution.worker.run(run_params, callback=callback)

    def __post_run(self, execution: Execution, callback: Callable) -> None:
        self.set_running_cb(execution, callback)

    def set_running_cb(self, execution: Execution, cb: Callable) -> None:
        self._running_cbs[str(execution.id)] = cb

    def get_running_cb(self, execution: Execution) -> Callable:
        return self._running_cbs.get(str(execution.id), lambda *args, **kwargs: None)

    def work(self, execution: Execution, callback=print) -> None:
        try:
            self.__pre_run(execution, callback=callback)
            self.__run(execution, callback=callback)
            self.__post_run(execution, callback=callback)
        except Exception as err:
            logger.error(f'{execution.asset} work failed: {err}')
            raise err
        finally:
            self.done(execution)

    def done(self, execution: Execution) -> None:
        # TODO 更新一下execution的状态
        pass

    def check(self):
        # TODO 定时检测 self._useless_workers 中的 Worker 活性
        pass


worker_pool = WorkerPool()
