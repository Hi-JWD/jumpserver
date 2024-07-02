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
from behemoth.tasks import run_task_sync
from behemoth.const import (
    CommandStatus, TaskStatus, FORMAT_COMMAND_CACHE_KEY, FILE_COMMAND_CACHE_KEY,
    CommandCategory, PlanCategory
)
from behemoth.libs.pools.worker import worker_pool
from behemoth.models import (
    Environment, Playback, Plan, Iteration, Execution, Command, SubPlan
)
from orgs.mixins.api import OrgBulkModelViewSet
from common.exceptions import JMSException, JMSObjectDoesNotExist
from common.utils import random_string
from orgs.utils import get_current_org_id


class EnvironmentViewSet(OrgBulkModelViewSet):
    model = Environment
    search_fields = ['name']
    serializer_classes = {
        'default': serializers.EnvironmentSerializer,
        'get_assets': serializers.AssetSerializer,
    }
    rbac_perms = {
        'get_assets': ['behemoth.view_environment']
    }

    @action(['GET', 'PATCH', 'DELETE'], detail=True, url_path='assets')
    def get_assets(self, request, *args, **kwargs):
        if request.method == 'GET':
            qs = self.get_object().assets.all()
            return self.get_paginated_response_from_queryset(qs)
        else:
            instance = self.get_object()
            serializer = serializers.AssetEnvironmentSerializer(data=request.data)
            if serializer.is_valid():
                assets = serializer.validated_data.get('assets')
                action_ = serializer.validated_data['action']
                if action_ == 'remove':
                    instance.assets.remove(*tuple(assets))
                else:
                    instance.assets.add(*tuple(assets))
                return Response(status=http_status.HTTP_200_OK)
            else:
                return Response(status=http_status.HTTP_400_BAD_REQUEST, data=serializer.errors)


class PlaybackViewSet(OrgBulkModelViewSet):
    model = Playback
    search_fields = ['name']
    serializer_classes = {
        'default': serializers.PlaybackSerializer,
        'get_deploy_tasks': serializers.ExecutionSerializer
    }
    rbac_perms = {
        'get_deploy_tasks': 'behemoth.view_execution',
    }

    @action(methods=['GET'], detail=True, url_path='deploy_tasks')
    def get_deploy_tasks(self, *args, **kwargs):
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
        if cmd.status == CommandStatus.success:
            worker_pool.record(execution, f'命令输入: {cmd.input}')
            worker_pool.record(execution, f'命令输出: {cmd.output}\n')
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
            worker_pool.record(execution, f'任务因为[{detail}]暂停: {cmd.output}')
        return Response(status=http_status.HTTP_200_OK, data={'status': can_continue, 'detail': detail})

    @action(methods=['GET'], detail=True, url_path='commands')
    def get_commands(self, request, *args, **kwargs):
        commands = self.get_object().get_commands()
        return self.get_paginated_response_from_queryset(commands)

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
        'default': serializers.PlanSerializer
    }


class SubPlanViewSet(OrgBulkModelViewSet):
    model = SubPlan
    ordering = '-serial'
    search_fields = ['name']
    filterset_fields = ['name']
    serializer_classes = {
        'default': serializers.SubPlanSerializer,
        'deploy_command': serializers.SubPlanCommandSerializer,
        'deploy_file': serializers.SubPlanFileSerializer,
    }
    rbac_perms = {
        'operate_commands': 'behemoth.change_command | behemoth.change_execution',
    }

    def get_queryset(self):
        plan_id = self.request.query_params.get('plan_id', '')
        if not plan_id:
            raise JMSObjectDoesNotExist(object_name=_('Plan'))
        return self.model.objects.filter(plan_id=plan_id)

    def create(self, request, *args, **kwargs):
        plan_id = request.query_params.get('plan_id', '')
        serializer = self.get_serializer(
            data={'plan': plan_id, **request.data}
        )
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=http_status.HTTP_201_CREATED)

    @staticmethod
    def start_execution(execution):
        if execution.status not in (TaskStatus.success, TaskStatus.executing):
            task = run_task_sync.delay(execution)
            execution.task_id = task.id
            execution.status = TaskStatus.executing
            execution.save(update_fields=['task_id', 'status'])
            return Response(status=http_status.HTTP_201_CREATED, data={'task_id': task.id})
        else:
            error = _('Task status: %s') % execution.status
            return Response({'error': error}, status=http_status.HTTP_400_BAD_REQUEST)

    @staticmethod
    def pause_execution(execution):
        execution.status = TaskStatus.pause
        execution.save(update_fields=['status'])
        return Response(status=http_status.HTTP_200_OK)

    @action(methods=['POST'], detail=True, url_path='operate_commands')
    def operate_commands(self, request, *args, **kwargs):
        action_ = request.data.get('action')
        execution = self.get_object().execution
        if action_ == 'start':
            response = self.start_execution(execution)
        elif action_ == 'pause':
            response = self.pause_execution(execution)
        else:
            data = {'error': 'Params action is not valid'}
            response = Response(status=http_status.HTTP_400_BAD_REQUEST, data=data)
        return response


class IterationViewSet(OrgBulkModelViewSet):
    model = Iteration
    search_fields = ['name']
    serializer_class = serializers.IterationSerializer
