import io
import os
import zipfile

from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import serializers as drf_serializer
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
    Environment, Playback, Plan, Iteration, Execution, Command,
    PlaybackExecution, MonthlyVersion
)
from common.utils import is_uuid, get_logger
from common.exceptions import JMSException
from common.utils.timezone import local_now_display
from orgs.mixins.api import OrgBulkModelViewSet
from orgs.utils import get_current_org_id


logger = get_logger(__file__)


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
            'task_id': task.id, 'task_status': TaskStatus.executing
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


class MonthlyVersionViewSet(OrgBulkModelViewSet):
    model = MonthlyVersion
    search_fields = ['name']
    serializer_classes = {
        'default': serializers.MonthlyVersionSerializer,
        'get_playbacks': serializers.SimplePlaybackSerializer,
    }
    rbac_perms = {
        'get_playbacks': ['behemoth.view_playbacks']
    }

    @action(methods=['PATCH', 'DELETE'], detail=True, url_path='playbacks')
    def get_playbacks(self, request, *args, **kwargs):
        obj = self.get_object()
        serializer = serializers.PlaybackMonthlyVersionSerializer(data=request.data)
        if serializer.is_valid():
            assets = serializer.validated_data.get('playbacks')
            action_ = serializer.validated_data['action']
            if action_ == 'remove':
                obj.playbacks.remove(*tuple(assets))
            else:
                obj.playbacks.add(*tuple(assets))
            return Response(status=http_status.HTTP_200_OK)
        else:
            return Response(status=http_status.HTTP_400_BAD_REQUEST, data=serializer.errors)


class PlaybackExecutionViewSet(OrgBulkModelViewSet):
    model = PlaybackExecution
    search_fields = ['plan_name', 'execution__version', 'execution__name']
    http_method_names = ('get', 'delete', 'head', 'options',)
    serializer_class = serializers.PlaybackExecutionSerializer

    def get_queryset(self):
        if self.request.method == 'DELETE':
            return self.model.objects.all()

        playback_id = self.request.query_params.get('playback_id')
        if not playback_id or not is_uuid(playback_id):
            raise JMSException('Query params playback_id is not uuid')
        return self.model.objects.filter(playback_id=playback_id)


class PlaybackViewSet(OrgBulkModelViewSet):
    model = Playback
    search_fields = ['name']
    filterset_fields = ['monthly_version']
    serializer_classes = {
        'default': serializers.PlaybackSerializer,
        'insert_pause': serializers.InsertPauseSerializer,
    }
    rbac_perms = {
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
        'format_commands': 'behemoth.view_command'
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
    ordering_fields = ('-date_created',)
    search_fields = ['name', 'version']
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
        return qs.order_by(*self.ordering_fields)

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

    @staticmethod
    def save_to_file(execution: Execution, data: dict):
        to = f'behemoth/output/{execution.id}/{data["command_id"]}.output'
        return default_storage.save(to, ContentFile(data['output']))

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

        output = data['output']
        if execution.category == ExecutionCategory.file:
            data['output'] = self.save_to_file(execution, data)

        fields = ['status', 'timestamp', 'output']
        for field in fields:
            setattr(cmd, field, data[field])
        cmd.save(update_fields=fields)
        if cmd.status == CommandStatus.success:
            input_msg = '%s:\n%s' % (_('Command input'), os.path.basename(cmd.input))
            worker_pool.record(execution, input_msg, 'cyan')
            worker_pool.record(execution, '%s:\n%s\n' % (_('Command output'), output), 'cyan')
        can_continue, detail = True, ''
        if data['status'] == CommandStatus.failed:
            can_continue = False
            detail = _('Failed')

        if not can_continue:
            execution.status = TaskStatus.pause
            execution.reason = '失败原因请查看命令结果'
            execution.save(update_fields=['status', 'reason'])
            worker_pool.record(execution, f'任务因为{detail}暂停:\n{output}', 'yellow')
            worker_pool.mark_task_status(execution.id, TaskStatus.failed)
        return Response(status=http_status.HTTP_200_OK, data={'status': can_continue, 'detail': detail})

    @action(methods=['GET'], detail=True, url_path='commands')
    def get_commands(self, request, *args, **kwargs):
        execution = self.get_object()
        commands = execution.get_commands()
        if execution.category == ExecutionCategory.file and len(commands) == 1:
            try:
                if (default_storage.exists(commands[0].input)
                        and not zipfile.is_zipfile(default_storage.path(commands[0].input))):
                    with default_storage.open(commands[0].input, 'r') as f:
                        commands[0].input = f.read()
                else:
                    commands[0].input = os.path.basename(commands[0].input)
                if commands[0].output and default_storage.exists(commands[0].output):
                    with default_storage.open(commands[0].output, 'r') as f:
                        commands[0].output = f.read()
                else:
                    commands[0].output = os.path.basename(commands[0].output)
            except Exception as e: # noqa
                logger.warning('Convert command error: %s', e)

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
    search_fields = ['name', 'created_by']
    filterset_fields = ['name', 'category']
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

    @staticmethod
    def _handle_zip_file(file, entry):
        with zipfile.ZipFile(file, 'r') as zip_file:
            new_zip_data = io.BytesIO()
            with zipfile.ZipFile(new_zip_data, 'w') as new_zip_file:
                for zip_info in zip_file.infolist():
                    with zip_file.open(zip_info.filename) as source_file:
                        new_zip_file.writestr(zip_info, source_file.read())
                new_zip_file.writestr('entry.bs', entry)
        new_zip_data.seek(0)
        return ContentFile(new_zip_data.read(), name=file.name)

    @action(['POST'], detail=True, url_path='upload')
    def upload_command_file(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data['file']
        if zipfile.is_zipfile(file):
            entry = serializer.validated_data['zip_entry_file']
            if not entry:
                raise drf_serializer.ValidationError(
                    _('The {} cannot be empty').format('zip_entry_file')
                )
            file = self._handle_zip_file(file, entry)

        name, ext = os.path.splitext(file.name)
        file_name = f'{name}-{local_now_display("%Y_%m_%d_%H_%M_%S")}{ext}'
        execution = self.get_object().create_execution(
            with_auth=True, name=file_name, category=ExecutionCategory.file,
            version=serializer.validated_data['version']
        )
        to = f'behemoth/commands/{execution.id}/{file_name}'
        relative_path = default_storage.save(to, file)
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
            cache.set(PLAN_TASK_ACTIVE_KEY.format(obj.id), user_set, timeout=wait_timeout * 24 * 7)
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
