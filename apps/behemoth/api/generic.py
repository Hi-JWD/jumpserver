import os

import sqlparse

from typing import AnyStr

from django.utils.translation import gettext as _
from django.core.cache import cache
from django.utils._os import safe_join
from django.conf import settings
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView
from rest_framework import status as http_status
from rest_framework import serializers as drf_serializers

from behemoth.backends import cmd_storage
from behemoth import serializers
from behemoth.const import (
    CommandStatus, TaskStatus, FORMAT_COMMAND_CACHE_KEY, FILE_COMMAND_CACHE_KEY,
    CommandCategory,
)
from behemoth.libs.pools.worker import worker_pool
from behemoth.models import Environment, Playback, Plan, Iteration, Execution
from common.api import JMSBulkModelViewSet
from common.exceptions import JMSException
from common.utils import random_string
from orgs.utils import get_current_org_id


class EnvironmentViewSet(JMSBulkModelViewSet):
    queryset = Environment.objects.all()
    search_fields = ['name']
    serializer_class = serializers.EnvironmentSerializer
    rbac_perms = {
        'get_assets': ['behemoth.view_environment']
    }

    @action(['GET'], detail=True, url_path='assets')
    def get_assets(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = serializers.AssetSerializer(
            instance.assets.all(), many=True
        )
        return Response(data=serializer.data)


class PlaybackViewSet(JMSBulkModelViewSet):
    queryset = Playback.objects.all()
    search_fields = ['name']
    serializer_class = serializers.PlaybackSerializer


class CommandUploadAPIView(APIView):
    rbac_perms = {
        'POST': ['behemoth.change_command'],
    }

    @staticmethod
    def cache_pause(mark_id, item):
        if not item:
            return

        cache_key = FILE_COMMAND_CACHE_KEY.format(mark_id)
        items = cache.get(cache_key, [])
        items.append(item)
        cache.set(cache_key, items, 3600)

    def post(self, request, *args, **kwargs):
        mark_id = request.data.get('mark_id', '')
        type_ = request.data.get('type')
        if type_ == 'pause':
            pause = request.data.get('pause', {})
            self.cache_pause(mark_id, {'category': CommandCategory.pause, **pause})
        else:
            files = request.FILES.getlist('files')
            if len(files) < 1:
                return Response(status=http_status.HTTP_400_BAD_REQUEST, data={'error': _('No file selected.')})

            upload_file_dir = safe_join(settings.SHARE_DIR, 'command_upload_file', mark_id)
            os.makedirs(upload_file_dir, exist_ok=True)
            file = files[0]
            saved_path = safe_join(upload_file_dir, f'{file.name}')
            with open(saved_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
            index = request.data.get('index')
            self.cache_pause(mark_id, {'filepath': saved_path, 'index': index, 'category': CommandCategory.file})
        return Response(status=http_status.HTTP_200_OK)


class CommandAPIView(APIView):
    rbac_perms = {
        'POST': ['behemoth.change_command'],
    }

    @staticmethod
    def convert_commands(commands: AnyStr):
        statements = sqlparse.split(commands)
        format_query = {
            'keyword_case': 'upper', 'strip_comments': True,
            'use_space_around_operators': True, 'strip_whitespace': True
        }
        return [sqlparse.format(s, **format_query) for s in statements]

    def post(self, request, *args, **kwargs):
        action_params = ('format',)
        action_ = request.query_params.get('action')
        if not action_:
            err_info = _("The parameter 'action' must be [{}]".format(','.join(action_params)))
            return Response(status=http_status.HTTP_400_BAD_REQUEST, data={'error', err_info})

        if action_ == 'format':
            token = random_string(16)
            commands = self.convert_commands(request.data['commands'])
            cache.set(FORMAT_COMMAND_CACHE_KEY.format(token), commands, 3600)
            return Response(data={'token': token, 'commands': commands})
        return Response(status=http_status.HTTP_400_BAD_REQUEST)


class ExecutionAPIView(GenericAPIView):
    queryset = Execution.objects.all()
    serializer_classes = {
        'status': serializers.ExecutionStatusSerializer,
        'command': serializers.ExecutionCommandSerializer,
    }

    def get_rbac_perms(self):
        default_perms = {
            'POST': 'behemoth.change_execution'
        }
        command_perms = {
            'POST': 'behemoth.change_command'
        }
        type_ = self.request.query_params.get('type')
        return command_perms if type_ == 'command' else default_perms

    def get_serializer_class(self):
        type_ = self.request.query_params.get('type')
        default = drf_serializers.Serializer
        return self.serializer_classes.get(type_, default)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        type_ = self.request.query_params.get('type')
        handler = getattr(self, f'_type_for_{type_}', None)
        if not handler:
            error = _('Task {} args or kwargs error').format(type_)
            raise JMSException(error)
        else:
            resp = handler(data=serializer.validated_data, execution=self.get_object())
            return resp or Response(status=http_status.HTTP_200_OK)

    @staticmethod
    def _type_for_status(execution, data, *args, **kwargs):
        execution.status = data['status']
        execution.reason = data['reason']
        execution.save(update_fields=['status', 'reason'])

    @staticmethod
    def _get_cmd(data, execution):
        # TODO 【命令缓存】在线执行的任务从缓存获取命令集合
        cmd = cmd_storage.get_queryset().filter(
            id=data['command_id'], execution_id=str(execution.id),
            org_id=str(get_current_org_id())
        ).first()
        return cmd

    def _type_for_command(self, execution, data, *args, **kwargs):
        cmd = self._get_cmd(data, execution)
        if not cmd:
            raise JMSException(_('%s object does not exist.') % data['command_id'])
        fields = ['status', 'timestamp']
        if cmd.category != CommandCategory.pause:
            fields.append('output')
        for field in fields:
            setattr(cmd, field, data[field])
        cmd.save(update_fields=fields)
        serializer = serializers.CommandSerializer(instance=cmd)
        worker_pool.refresh_task_info(execution, 'command_cb', serializer.data)

        can_continue, detail = True, ''
        # 任务被手动暂停或者命令类型为“暂停”并开启暂停才不能继续执行
        if execution.status == TaskStatus.pause or cmd.pause:
            can_continue = False
            detail = _('Paused')
        elif data['status'] == CommandStatus.failed:
            can_continue = False
            detail = _('Failed')

        if not can_continue:
            execution.status = TaskStatus.pause
            execution.reason = data['output']
            execution.save(update_fields=['status', 'reason'])
            worker_pool.refresh_task_info(execution, 'pause', cmd.output)
        return Response(status=http_status.HTTP_200_OK, data={'status': can_continue, 'detail': detail})

    @staticmethod
    def _type_for_health(execution, *args, **kwargs):
        # TODO 想办法证明这个任务正在执行，这个接口10秒1次
        pass


class PlanViewSet(JMSBulkModelViewSet):
    queryset = Plan.objects.all()
    search_fields = ['name']
    filterset_fields = ['name', 'category']
    serializer_class = serializers.PlanSerializer

    def get_serializer_class(self):
        task_type = self.request.query_params.get('task_type')
        serializer_class = serializers.PlanSerializer
        if task_type == 'deploy_file':
            serializer_class = serializers.FilePlanSerializer
        return serializer_class


class IterationViewSet(JMSBulkModelViewSet):
    queryset = Iteration.objects.all()
    search_fields = ['name']
    serializer_class = serializers.IterationSerializer
