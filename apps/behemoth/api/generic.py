from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.generics import GenericAPIView
from rest_framework import status as http_status
from rest_framework import serializers as drf_serializers
from django.utils.translation import gettext as _

from behemoth.backends import cmd_storage
from behemoth import serializers
from behemoth.libs.pools.worker import worker_pool
from behemoth.models import Environment, Playback, Plan, Iteration, Execution
from common.api import JMSBulkModelViewSet
from common.exceptions import JMSException
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


class ExecutionAPIView(GenericAPIView):
    queryset = Execution.objects.all()
    rbac_perms = {
        'POST': 'behemoth.change_execution'
    }
    serializer_classes = {
        'status': serializers.ExecutionStatusSerializer,
        'command': serializers.ExecutionCommandSerializer,
    }

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
            handler(data=serializer.validated_data, execution=self.get_object())
            return Response(status=http_status.HTTP_200_OK)

    @staticmethod
    def _type_for_play(execution, *args, **kwargs):
        worker_pool.work(execution)

    @staticmethod
    def _type_for_status(execution, data, *args, **kwargs):
        execution.status = data['status']
        execution.save(update_fields=['status'])

    @staticmethod
    def _type_for_command(execution, data, *args, **kwargs):
        cmd = cmd_storage.filter(
            id=data['command_id'], execution_id=str(execution.id),
            org_id=str(get_current_org_id()), without_timestamp=True
        ).first()
        if not cmd:
            raise JMSException(_('%s object does not exist.') % data['command_id'])
        cmd.status = data['status']
        cmd.output = data['result']
        cmd.save(update_fields=['status', 'output'])

    @staticmethod
    def _type_for_health(execution, *args, **kwargs):
        # TODO 想办法证明这个任务正在执行，这个接口10秒1次
        pass


class PlanViewSet(JMSBulkModelViewSet):
    queryset = Plan.objects.all()
    search_fields = ['name']
    filterset_fields = ['name', 'category']
    serializer_class = serializers.PlanSerializer
    rbac_perms = {
        'get_commands': ['behemoth.view_plan', 'behemoth.view_instruction']
    }

    @action(['GET'], detail=True, url_path='commands')
    def get_commands(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = serializers.CommandSerializer(
            instance.get_commands(), many=True
        )
        return Response(data=serializer.data)


class IterationViewSet(JMSBulkModelViewSet):
    queryset = Iteration.objects.all()
    search_fields = ['name']
    serializer_class = serializers.IterationSerializer
