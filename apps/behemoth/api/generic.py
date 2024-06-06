from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import views
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from common.api import JMSBulkModelViewSet
from .. import serializers
from ..libs.pools.worker import worker_pool
from ..models import Environment, Playback, Execution, Plan, Iteration


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


class ExecutionAPIView(views.APIView):
    rbac_perms = {
        'POST': 'behemoth.add_execution'
    }

    @staticmethod
    def post(request, execution_id, *args, **kwargs):
        action_ = request.query_params.get('action')
        if action_ == 'play':
            execution = get_object_or_404(Execution, pk=execution_id)
            worker_pool.work(execution)
        else:
            error = _('Task {} args or kwargs error').format(action_)
            return Response(status=status.HTTP_400_BAD_REQUEST, data={'error': error})
        return Response(status=status.HTTP_200_OK)


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
