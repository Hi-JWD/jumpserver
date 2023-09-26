from django.http import FileResponse, HttpResponse
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import escape_uri_path
from django.core.files.storage import default_storage
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.viewsets import ModelViewSet
from common.utils.http import is_true

from common.const.choices import Trigger
from common.const.http import GET
from common.api import JMSModelViewSet
from common.utils.timezone import local_now_display
from common.utils import get_logger
from rbac.permissions import RBACPermission
from reports import serializers
from reports.models import Report, ReportExecution
from reports.tasks.report.common import get_report_templates
from reports.tasks import execute_report_task


logger = get_logger(__file__)


class ReportViewSet(JMSModelViewSet):
    queryset = Report.objects.all()
    serializer_class = serializers.ReportSerializer
    filterset_fields = ['name']
    rbac_perms = {
        'categories': 'reports.view_report',
    }

    @action(methods=['get'], detail=False, permission_classes=[RBACPermission])
    def categories(self, request, *args, **kwargs):
        templates = get_report_templates()
        data = [
            {'id': _id, 'name': _class.NAME} for _id, _class in templates.items()
        ]
        return Response(data=data)


class ReportExecutionViewSet(ModelViewSet):
    queryset = ReportExecution.objects.all()
    serializer_class = serializers.ReportExecutionSerializer
    search_fields = ('trigger', 'report__name')
    filterset_fields = ('trigger', 'report_id', 'report__name')
    rbac_perms = {
        'download': 'report.view_reportexecution',
    }

    def create(self, request, *args, **kwargs):
        async_task = self.request.query_params.get('async', True)
        report_id = self.request.data.get('report')
        if is_true(async_task):
            task = execute_report_task.delay(rid=str(report_id), trigger=Trigger.manual)
            return Response({'task': task.id}, status=status.HTTP_201_CREATED)
        else:
            execution = execute_report_task(
                rid=str(report_id), trigger=Trigger.manual
            )
            serializer = self.serializer_class(instance=execution)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        methods=[GET], detail=True, url_path='file/download',
        permission_classes=[RBACPermission, ],
    )
    def download(self, request, *args, **kwargs):
        instance = self.get_object()
        local_path = instance.result.get('filepath')
        try:
            file = open(default_storage.path(local_path), 'rb')
        except Exception as err:
            logger.error(f'User({request.user}) failed to find this path: {local_path}. Error: {err}')
            return HttpResponse(status=status.HTTP_404_NOT_FOUND)

        response = FileResponse(file)
        response['Content-Type'] = 'application/octet-stream'
        filename = escape_uri_path(f'{instance.report_type}_{local_now_display()}')
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{filename}.pdf"
        return response
