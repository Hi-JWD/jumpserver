# coding:utf-8
from django.urls import path
from rest_framework_bulk.routes import BulkRouter

from .. import api

app_name = 'behemoth'

router = BulkRouter()

router.register(r'environments', api.EnvironmentViewSet, 'environment')
router.register(r'playbacks', api.PlaybackViewSet, 'playback')
router.register(r'plans', api.PlanViewSet, 'plan')
router.register(r'iterations', api.IterationViewSet, 'iteration')

urlpatterns = [
    path('executions/<uuid:pk>/', api.ExecutionAPIView.as_view(), name='execution'),
    path('commands/', api.CommandAPIView.as_view(), name='command'),
    path('commands/upload/', api.CommandUploadAPIView.as_view(), name='upload-command-file'),
]

urlpatterns += router.urls
