# -*- coding: utf-8 -*-
#
from rest_framework_bulk.routes import BulkRouter

from .. import api

app_name = 'reports'
router = BulkRouter()

router.register('reports', api.ReportViewSet, 'report')
router.register('report-executions', api.ReportExecutionViewSet, 'report-executions')

urlpatterns = []
urlpatterns += router.urls
