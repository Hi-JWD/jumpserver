import os

from django.utils.translation import gettext as _
from django.core.cache import cache
from django.utils._os import safe_join
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status as http_status

from behemoth.backends import cmd_storage
from behemoth import serializers
from behemoth.tasks import run_task_sync
from behemoth.const import (
    CommandStatus, TaskStatus, FILE_COMMAND_CACHE_KEY,
    CommandCategory, PlanCategory, PLAN_TASK_ACTIVE_KEY
)
from behemoth.libs.pools.worker import worker_pool
from behemoth.models import (
    Environment, Playback, Plan, Iteration, SyncPlanCommandRelation,
    Execution, Command
)
from common.management.commands import status
from common.utils import is_uuid
from common.exceptions import JMSException, JMSObjectDoesNotExist
from orgs.mixins.api import OrgBulkModelViewSet
from orgs.utils import get_current_org_id


class ExecutionMixin:
    @staticmethod
    def start_task(execution: Execution, response_data: dict | None = None):
        if execution.status not in (TaskStatus.success, TaskStatus.executing):
            params = {}
            if execution.task_id:
                params['task_id'] = execution.task_id
            # task = run_task_sync.apply_async((execution,), **params)
            task = run_task_sync(execution)
            execution.task_id = task.id
            execution.status = TaskStatus.executing
            execution.save(update_fields=['task_id', 'status'])
            data = {
                'task_id': task.id, 'task_status': TaskStatus.executing
            }
            if response_data:
                data.update(response_data)
            return Response(status=http_status.HTTP_201_CREATED, data=data)
        else:
            error = _('Task status: %s') % execution.status
            return Response({'error': error}, status=http_status.HTTP_400_BAD_REQUEST)


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
        'get_playbacks_tasks': serializers.PlaybackExecutionSerializer,
        'insert_pause': serializers.InsertPauseSerializer,
    }
    rbac_perms = {
        'get_playbacks_tasks': 'behemoth.view_execution',
        'insert_pause': 'behemoth.add_execution',
    }

    @action(methods=['GET'], detail=True, url_path='playback_tasks')
    def get_playbacks_tasks(self, *args, **kwargs):
        qs = self.get_object().executions.all()
        return self.get_paginated_response_from_queryset(qs)

    @action(methods=['POST'], detail=True, url_path='insert_pause')
    def insert_pause(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.get_object().create_pause(serializer.data)
        return Response(status=http_status.HTTP_201_CREATED)


class CommandViewSet(OrgBulkModelViewSet):
    model = Command
    serializer_classes = (
        ('default', serializers.CommandSerializer),
        ('upload_commands', serializers.UploadCommandSerializer),
        ('format_commands', serializers.FormatCommandSerializer),
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

    @action(['POST'], detail=False, url_path='format')
    def format_commands(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(data=serializer.data)

    @action(['POST'], detail=False, url_path='upload')
    def upload_commands(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
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


class ExecutionViewSet(ExecutionMixin ,OrgBulkModelViewSet):
    model = Execution
    search_fields = ['name']
    filterset_fields = ['name']
    serializer_classes = {
        'default': serializers.ExecutionSerializer,
        'update_command': serializers.ExecutionCommandSerializer,
        'get_commands': serializers.CommandSerializer,
        'deploy_command': serializers.CommandExecutionSerializer,
        'deploy_file': serializers.FileExecutionSerializer,
    }
    rbac_perms = {
        'update_command': 'behemoth.change_command',
        'get_commands': 'behemoth.view_command',
        'operate_task': 'behemoth.change_command | behemoth.change_execution',
    }

    def get_queryset(self):
        plan_id = self.request.query_params.get('plan_id', '')
        qs = self.model.objects.all()
        if is_uuid(plan_id):
            qs = qs.filter(plan_id=plan_id)
        return qs

    def create(self, request, *args, **kwargs):
        plan_id = request.query_params.get('plan_id', '')
        serializer = self.get_serializer(
            data={'plan': plan_id, **request.data}
        )
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=http_status.HTTP_201_CREATED)

    @staticmethod
    def pause_execution(execution):
        if execution.status != TaskStatus.executing:
            error = _('Task status: %s') % execution.status
            return Response({'error': error}, status=http_status.HTTP_400_BAD_REQUEST)

        execution.status = TaskStatus.pause
        execution.save(update_fields=['status'])
        worker_pool.record(execution, f'任务被手动暂停了', color='yellow')
        return Response(status=http_status.HTTP_200_OK, data={
            'task_status': TaskStatus.pause
        })

    @action(methods=['POST'], detail=True, url_path='operate_task')
    def operate_task(self, request, *args, **kwargs):
        action_ = request.data.get('action')
        if action_ == 'start':
            response = self.start_task(self.get_object())
        elif action_ == 'pause':
            response = self.pause_execution(self.get_object())
        elif action_ == 'success':
            execution = self.get_object()
            execution.status = TaskStatus.success
            execution.save(update_fields=['status'])
            worker_pool.record(execution, f'任务执行成功', color='green')
            response = Response(status=http_status.HTTP_200_OK, data={
                'task_status': TaskStatus.success
            })
        else:
            data = {'error': 'Params action is not valid'}
            response = Response(status=http_status.HTTP_400_BAD_REQUEST, data=data)
        return response

    @action(methods=['PATCH'], detail=True, url_path='command')
    def update_command(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
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
        plan_category = execution.plan.category
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
        relation_id = request.query_params.get('relation_id')
        commands = self.get_object().get_commands()
        if relation_id:
            commands = commands.filter(relation_id=relation_id)
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


class PlanViewSet(ExecutionMixin, OrgBulkModelViewSet):
    model = Plan
    search_fields = ['name']
    filterset_fields = ['name']
    serializer_classes = {
        'default': serializers.DeployPlanSerializer,
        'deploy': serializers.DeployPlanSerializer,
        'sync': serializers.SyncPlanSerializer,
    }
    rbac_perms = {
        'start_sync_task': 'behemoth.change_execution',
    }

    def get_queryset(self):
        qs = self.model.objects.all()
        if category := self.request.query_params.get('action'):
            qs = qs.filter(category=category)
        return qs

    @action(methods=['POST'], detail=True, url_path='start-sync-task')
    def start_sync_task(self, request, *args, **kwargs):
        obj = self.get_object()
        users = cache.get(PLAN_TASK_ACTIVE_KEY.format(obj.id), [])
        users.append(f'{request.user.name}({request.user.username})')
        result = list(set(users))
        participants = settings.SYNC_PLAN_REQUIRED_PARTICIPANTS
        wait_timeout = settings.SYNC_PLAN_WAIT_PARTICIPANT_IDLE
        if len(result) >= participants:
            cache.set(PLAN_TASK_ACTIVE_KEY.format(obj.id), [], timeout=wait_timeout)
            return self.start_task(
                obj.executions.first(), response_data={'users': [str(request.user)]}
            )
        else:
            cache.set(PLAN_TASK_ACTIVE_KEY.format(obj.id), result, timeout=wait_timeout)
        data = {
            'ttl': wait_timeout, 'users': result,
            'participants': participants, 'wait_timeout': wait_timeout
        }
        return Response(status=http_status.HTTP_200_OK, data=data)


class IterationViewSet(OrgBulkModelViewSet):
    model = Iteration
    search_fields = ['name']
    serializer_class = serializers.IterationSerializer


class SyncPlanRelationTree(APIView):
    rbac_perms = {
        'GET': 'behemoth.view_syncplancommandrelation'
    }

    @staticmethod
    def get(request, *args, **kwargs):
        tree_data = []
        plan_id = request.query_params.get('plan_id')
        if not is_uuid(plan_id):
            raise JMSObjectDoesNotExist(object_name=_('Plan'))

        qs = SyncPlanCommandRelation.objects.filter(sync_plan_id=plan_id)
        for i, obj in enumerate(qs, 1):
            label = obj.plan_name or _('Special')
            tree_data.append({
                'id': f'1{i}', 'name': label, 'value': obj.id, 'pId': '0', 'open': False,
            })
        return Response(data=tree_data)
