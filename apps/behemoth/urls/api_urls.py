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


def test(*args, **kwargs):
    from django.http.response import HttpResponse
    from behemoth.tasks import test
    test.delay()
    return HttpResponse(b'ok')


urlpatterns = [
    path('sync-plan/relation/tree/', api.SyncPlanRelationTree.as_view(), name='sync-plan-tree'),
    path('test/', test)
]

urlpatterns += router.urls
