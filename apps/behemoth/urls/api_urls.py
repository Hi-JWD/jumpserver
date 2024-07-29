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
router.register(r'commands', api.CommandViewSet, 'command')
router.register(r'executions', api.ExecutionViewSet, 'executions')


urlpatterns = [
    path('index/', api.IndexApi.as_view()),
]

urlpatterns += router.urls
