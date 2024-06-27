# -*- coding: utf-8 -*-
#
import json

from channels.generic.websocket import JsonWebsocketConsumer
from django.utils.translation import gettext as _
from rest_framework.utils.encoders import JSONEncoder
from celery.result import AsyncResult, states

from behemoth.const import TaskStatus
from behemoth.models import Execution, Plan
from behemoth.serializers import CommandSerializer
from behemoth.libs.pools.worker import worker_pool
from behemoth.tasks import run_task_sync
from common.db.utils import close_old_connections
from common.utils import get_logger
from ops.celery import app


logger = get_logger(__name__)


class ExecutionWebsocket(JsonWebsocketConsumer):
    _execution: Execution | None = None
    _plan: Plan | None = None

    def connect(self):
        user = self.scope["user"]
        if user.is_authenticated:
            self.accept()
        else:
            self.close()

    def get_obj(self, obj_id, model, bind_attr):
        if obj := getattr(self, bind_attr) is not None:
            return obj

        obj = model.objects.filter(id=obj_id).first()
        setattr(self, bind_attr, obj)
        if getattr(self, bind_attr) is None:
            self.send_json({'type': 'error', 'message': _('%s object does not exist.') % obj_id})
            self.close()
        return obj

    def receive_json(self, content=None, **kwargs):
        type_ = content.get('type')
        execution_id = content.get('execution_id')
        try:
            if type_ == 'get_commands':
                execution = self.get_obj(execution_id, Execution, '_execution')
                commands = execution.get_commands()
                serializer = CommandSerializer(commands, many=True)
                self.send_json({'type': type_, 'data': serializer.data})
            elif type_ == 'run':
                execution = self.get_obj(execution_id, Execution, '_execution')
                if execution.status not in (TaskStatus.success, TaskStatus.executing):
                    worker_pool.refresh_task_info(execution, 'show_tip', '', ttl=1)
                    execution.status = TaskStatus.executing
                    execution.save(update_fields=['status'])
                    task_id = run_task_sync.delay(execution)
                    self.send_json({'type': 'show_tip', 'data': {'task_id': task_id.id}})
                else:
                    self.send_json({'type': 'error', 'data': _('Task status: %s') % execution.status})
            elif type_ == 'pause':
                execution = self.get_obj(execution_id, Execution, '_execution')
                execution.status = TaskStatus.pause
                execution.save(update_fields=['status'])
                self.send_json({'type': type_, 'data': ''})
            elif type_ == 'info':
                execution = self.get_obj(execution_id, Execution, '_execution')
                self.send_json(worker_pool.get_task_info(execution))
            elif type_ == 'task_status':
                task_id = content.get('task_id')
                if not task_id:
                    return

                result = AsyncResult(task_id, app=app)
                self.send_json({'type': type_, 'data': {'status': result.status}})
        except Exception as e:
            logger.error('Behemoth ws error: %s' % e)
            self.send_json({'type': 'error', 'data': str(e)})
            self.disconnect()

    @classmethod
    def encode_json(cls, content):
        return json.dumps(content, cls=JSONEncoder)

    def disconnect(self, code=None):
        self.close()
        close_old_connections()
