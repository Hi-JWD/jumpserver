from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
from django.conf import settings
from django.core.files.storage import default_storage
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status as http_status

from behemoth.backends import cmd_storage
from behemoth import serializers
from behemoth.tasks import run_task_sync
from behemoth.const import (
    CommandStatus, TaskStatus, FILE_COMMAND_CACHE_KEY,
    PLAN_TASK_ACTIVE_KEY, ExecutionCategory
)
from behemoth.libs.pools.worker import worker_pool
from behemoth.models import (
    Environment, Playback, Plan, Iteration, Execution, Command
)
from common.utils import is_uuid
from common.exceptions import JMSException
from common.utils.timezone import local_now_display
from orgs.mixins.api import OrgBulkModelViewSet
from orgs.utils import get_current_org_id


class ExecutionMixin:
    @staticmethod
    def start_task(
            executions: list[Execution], users: list, response_data: dict | None = None
    ):
        valid_executions = [
            e for e in executions if e.status not in (TaskStatus.success, TaskStatus.executing)
        ]
        if not valid_executions:
            error = _('Task is running or finished')
            return Response({'error': error}, status=http_status.HTTP_400_BAD_REQUEST)

        task_params = {}
        if executions[0].task_id:
            task_params['task_id'] = executions[0].task_id

        task = run_task_sync.apply_async((valid_executions, users), **task_params)
        # task = run_task_sync(valid_executions, users)
        for execution in valid_executions:
            if not execution.task_id:
                execution.task_id = task.id
                execution.save(update_fields=['task_id'])
        data = {
            'task_id': task.id, 'task_status': valid_executions[0].status
        }
        if response_data:
            data.update(response_data)
        return Response(status=http_status.HTTP_201_CREATED, data=data)


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
        ('format_commands', serializers.FormatCommandSerializer),
    )
    rbac_perms = {
        'format_commands': 'behemoth.view_command',
        'upload_commands': 'behemoth.add_command',
    }

    def allow_bulk_destroy(self, qs, filtered):
        return False

    def perform_destroy(self, instance):
        instance.has_delete = True
        instance.save(update_fields=['has_delete'])

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


class ExecutionViewSet(ExecutionMixin, OrgBulkModelViewSet):
    model = Execution
    ordering_fields = ('date_created',)
    search_fields = ['name']
    filterset_fields = ['name', 'status']
    serializer_classes = {
        'default': serializers.ExecutionSerializer,
        'update_command': serializers.ExecutionCommandSerializer,
        'get_commands': serializers.CommandSerializer,
        'deploy_command': serializers.CommandExecutionSerializer,
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
            response = self.start_task([self.get_object()], [str(request.user)])
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
        fields = ['status', 'timestamp', 'output']
        for field in fields:
            setattr(cmd, field, data[field])
        cmd.save(update_fields=fields)
        if cmd.status == CommandStatus.success:
            worker_pool.record(execution, '%s:\n%s' % (_('Command input'), cmd.input))
            worker_pool.record(execution, '%s:\n%s\n' % (_('Command output'), cmd.output))
        can_continue, detail = True, ''
        if data['status'] == CommandStatus.failed:
            can_continue = False
            detail = _('Failed')

        if not can_continue:
            execution.status = TaskStatus.pause
            execution.reason = data['output']
            execution.save(update_fields=['status', 'reason'])
            worker_pool.record(execution, f'任务暂停({detail}): {cmd.output}', 'yellow')
            worker_pool.mark_task_status(execution.id, TaskStatus.failed)
        return Response(status=http_status.HTTP_200_OK, data={'status': can_continue, 'detail': detail})

    @action(methods=['GET'], detail=True, url_path='commands')
    def get_commands(self, request, *args, **kwargs):
        execution = self.get_object()
        commands = execution.get_commands()
        if execution.category == ExecutionCategory.file and len(commands) == 1:
            if not default_storage.exists(commands[0].input):
                commands = []
            else:
                with open(default_storage.path(commands[0].input)) as f:
                    commands[0].input = f.read()
        serializer = self.get_serializer(commands, many=True)
        return Response({'results': serializer.data, 'category': execution.category})

    @staticmethod
    def _get_cmd(data, execution):
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
        'upload_command_file': serializers.SyncPlanUploadSerializer,
    }
    rbac_perms = {
        'start_sync_task': 'behemoth.change_execution',
        'upload_command_file': ['behemoth.add_plan', 'behemoth.add_execution', 'behemoth.add_command']
    }

    def get_queryset(self):
        qs = self.model.objects.all()
        if category := self.request.query_params.get('action'):
            qs = qs.filter(category=category)
        return qs

    @action(['POST'], detail=True, url_path='upload')
    def upload_command_file(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data['file']
        file_name = f'{file.name}({local_now_display("%Y-%m-%d-%H:%M:%S")})'
        to = f'behemoth/commands/{file_name}'
        relative_path = default_storage.save(to, file)
        execution = self.get_object().create_execution(
            with_auth=True, name=file_name, category=ExecutionCategory.file,
            version=serializer.validated_data['version']
        )
        Command.objects.create(
            input=f'{relative_path}', index=0, execution_id=execution.id,
        )
        return Response(serializer.data, status=http_status.HTTP_201_CREATED)

    @action(methods=['POST'], detail=True, url_path='start-sync-task')
    def start_sync_task(self, request, *args, **kwargs):
        obj = self.get_object()
        users = cache.get(PLAN_TASK_ACTIVE_KEY.format(obj.id), [])
        users.append(f'{request.user.name}({request.user.username})')
        user_set = list(set(users))
        participants = getattr(settings, 'SYNC_PLAN_REQUIRED_PARTICIPANTS', 2)
        wait_timeout = getattr(settings, 'SYNC_PLAN_WAIT_PARTICIPANT_IDLE', 3600)
        if len(user_set) >= participants:
            cache.set(PLAN_TASK_ACTIVE_KEY.format(obj.id), [], timeout=3600 * 24 * 7)
            return self.start_task(
                obj.executions.all(), user_set, response_data={'users': [str(request.user)]}
            )
        else:
            cache.set(PLAN_TASK_ACTIVE_KEY.format(obj.id), user_set, timeout=wait_timeout)
        data = {
            'ttl': wait_timeout, 'users': user_set,
            'participants': participants, 'wait_timeout': wait_timeout
        }
        return Response(status=http_status.HTTP_200_OK, data=data)


class IterationViewSet(OrgBulkModelViewSet):
    model = Iteration
    search_fields = ['name']
    serializer_class = serializers.IterationSerializer
