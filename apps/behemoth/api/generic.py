import os

import sqlparse

from typing import AnyStr

from django.utils.translation import gettext as _
from django.core.cache import cache
from django.utils._os import safe_join
from django.conf import settings
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status as http_status

from behemoth.backends import cmd_storage
from behemoth import serializers
from behemoth.const import (
    CommandStatus, TaskStatus, FORMAT_COMMAND_CACHE_KEY, FILE_COMMAND_CACHE_KEY,
    CommandCategory, PlanCategory
)
from behemoth.libs.pools.worker import worker_pool
from behemoth.models import (
    Environment, Playback, Plan, Iteration, Execution, Command
)
from orgs.mixins.api import OrgBulkModelViewSet
from common.exceptions import JMSException
from common.utils import random_string
from orgs.utils import get_current_org_id


class EnvironmentViewSet(OrgBulkModelViewSet):
    model = Environment
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


class PlaybackViewSet(OrgBulkModelViewSet):
    model = Playback
    search_fields = ['name']
    serializer_classes = {
        'default': serializers.PlaybackSerializer,
        'get_tasks': serializers.ExecutionSerializer
    }
    rbac_perms = {
        'get_tasks': 'behemoth.view_execution',
    }

    @action(methods=['GET'], detail=True, url_path='deploy_tasks')
    def get_tasks(self, *args, **kwargs):
        instance = self.get_object()
        qs = Execution.objects.filter(playback_id=instance.id)
        return self.get_paginated_response_from_queryset(qs)


class CommandViewSet(OrgBulkModelViewSet):
    model = Command
    serializer_classes = (
        ('default', serializers.CommandSerializer),
        ('upload_commands', serializers.UploadCommandSerializer),
    )
    rbac_perms = {
        'format_commands': 'behemoth.view_command',
        'upload_commands': 'behemoth.add_command',
    }

    @staticmethod
    def cache_command(mark_id, item):
        if not item:
            return

        cache_key = FILE_COMMAND_CACHE_KEY.format(mark_id)
        items = cache.get(cache_key, [])
        items.append(item)
        cache.set(cache_key, items, 3600)

    @staticmethod
    def convert_commands(commands: AnyStr):
        statements = sqlparse.split(commands)
        format_query = {
            'keyword_case': 'upper', 'strip_comments': True,
            'use_space_around_operators': True, 'strip_whitespace': True
        }
        return [sqlparse.format(s, **format_query) for s in statements]

    @action(['POST'], detail=False, url_path='format')
    def format_commands(self, request, *args, **kwargs):
        token = random_string(16)
        commands = self.convert_commands(request.data['commands'])
        cache.set(FORMAT_COMMAND_CACHE_KEY.format(token), commands, 3600)
        return Response(data={'token': token, 'commands': commands})

    @action(['POST'], detail=False, url_path='upload')
    def upload_commands(self, request, *args, **kwargs):
        serializer = self.get_serializer_class()(data=request.data)
        mark_id = serializer.data['mark_id']
        action_ = serializer.data['action']
        if action_ == 'cache_pause':
            pause = request.data.get('pause', {})
            self.cache_command(mark_id, {'category': CommandCategory.pause, **pause})
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
            item = {
                'index': serializer.data['index'],
                'filepath': saved_path, 'category': CommandCategory.file
            }
            self.cache_command(mark_id, item)
        return Response(status=http_status.HTTP_200_OK)


class ExecutionViewSet(OrgBulkModelViewSet):
    model = Execution
    serializer_classes = {
        'default': serializers.ExecutionSerializer,
        'update_command': serializers.ExecutionCommandSerializer,
        'get_commands': serializers.CommandSerializer
    }
    rbac_perms = {
        'update_command': 'behemoth.change_command',
        'get_commands': 'behemoth.view_command',
    }

    @action(methods=['PATCH'], detail=True, url_path='command')
    def update_command(self, request, *args, **kwargs):
        serializer = self.get_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        execution = self.get_object()
        if execution.status != TaskStatus.executing:
            message = _('The task is not running!')
            return Response(
                status=http_status.HTTP_200_OK, data={'status': False, 'detail': message}
            )
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
        # 任务被手动暂停或者命令类型为“暂停”并开启暂停才不能继续执行[任务为同步类型]
        plan_category = execution.plan_meta.get('category')
        if execution.status == TaskStatus.pause:
            can_continue = False
            detail = _('Manual paused')
        elif plan_category == PlanCategory.sync and cmd.pause:
            can_continue = False
            detail = _('Command paused')
        elif data['status'] == CommandStatus.failed:
            can_continue = False
            detail = _('Failed')

        if not can_continue:
            execution.status = TaskStatus.pause
            execution.reason = data['output']
            execution.save(update_fields=['status', 'reason'])
            worker_pool.refresh_task_info(execution, 'pause', cmd.output)
        return Response(status=http_status.HTTP_200_OK, data={'status': can_continue, 'detail': detail})

    @action(methods=['GET'], detail=True, url_path='commands')
    def get_commands(self, request, *args, **kwargs):
        commands = self.get_object().get_commands()
        serializer = self.get_serializer_class()(commands, many=True)
        return Response(status=http_status.HTTP_200_OK, data=serializer.data)

    @staticmethod
    def _get_cmd(data, execution):
        # TODO 【命令缓存】在线执行的任务从缓存获取命令集合
        return cmd_storage.get_queryset().filter(
            id=data['command_id'], execution_id=str(execution.id),
            org_id=str(get_current_org_id())
        ).first()

    @staticmethod
    def _type_for_health(execution, *args, **kwargs):
        # TODO 想办法证明这个任务正在执行，这个接口10秒1次
        pass


class PlanViewSet(OrgBulkModelViewSet):
    model = Plan
    search_fields = ['name']
    filterset_fields = ['name', 'category']
    serializer_classes = {
        'default': serializers.PlanSerializer,
    }
    rbac_perms = {
        'get_sub_plans': 'behemoth.view_subplan',
    }

    def get_serializer_class(self):
        task_type = self.request.query_params.get('task_type')
        serializer_class = serializers.PlanSerializer
        if task_type == 'deploy_file':
            serializer_class = serializers.FilePlanSerializer
        return serializer_class

    def get_queryset(self):
        return super().get_queryset().order_by('-date_created')

    @action(methods=['GET'], detail=True, url_path='sub-plans')
    def get_sub_plans(self, request, *args, **kwargs):
        obj = self.get_object()
        serializer = serializers.SubPlanSerializer(obj.subs, many=True)
        return Response({'results': serializer.data})

    @action(methods=['POST'], detail=True, url_path='deploy_command')
    def append_cmd_deploy(self, request, *args, **kwargs):
        pass


class IterationViewSet(OrgBulkModelViewSet):
    model = Iteration
    search_fields = ['name']
    serializer_class = serializers.IterationSerializer
