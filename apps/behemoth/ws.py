# -*- coding: utf-8 -*-
#
import json

from channels.generic.websocket import JsonWebsocketConsumer
from django.utils.translation import gettext as _
from rest_framework.utils.encoders import JSONEncoder

from behemoth.const import TaskStatus
from behemoth.models import Execution
from behemoth.serializers import CommandSerializer
from behemoth.libs.pools.worker import worker_pool
from common.db.utils import close_old_connections
from common.utils import get_logger


logger = get_logger(__name__)


class ExecutionWebsocket(JsonWebsocketConsumer):
    _execution: Execution | None = None

    def connect(self):
        user = self.scope["user"]
        if user.is_authenticated:
            self.accept()
        else:
            self.close()

    def get_execution(self, execution_id):
        if self._execution is not None:
            return self._execution

        self._execution = Execution.objects.filter(id=execution_id).first()
        if self._execution is None:
            self.send_json({'type': 'error', 'message': _('%s object does not exist.') % execution_id})
            self.close()
        return self._execution

    def send_tip(self, content, msg_type='show_tip'):
        self.send_json({'type': msg_type, 'data': content})

    def receive_json(self, content=None, **kwargs):
        type_ = content.get('type')
        execution_id = content.get('execution_id')
        try:
            if type_ == 'get_commands':
                execution = self.get_execution(execution_id)
                commands = execution.get_commands()
                serializer = CommandSerializer(commands, many=True)
                self.send_json({'type': type_, 'data': serializer.data})
            elif type_ == 'run_execution':
                execution = self.get_execution(execution_id)
                if execution.status == TaskStatus.not_started:
                    worker_pool.work(execution, callback=self.send_tip)
                    self.send_json({'type': type_, 'data': 'ok'})
        except Exception as e:
            self.send_json({'type': 'error', 'data': str(e)})
            self.close()

    @classmethod
    def encode_json(cls, content):
        return json.dumps(content, cls=JSONEncoder)

    def disconnect(self, code):
        self.close()
        close_old_connections()
