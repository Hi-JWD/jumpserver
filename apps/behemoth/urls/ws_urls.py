from django.urls import path

from .. import ws

app_name = 'behemoth'

urlpatterns = [
    path('ws/behemoth/executions/', ws.ExecutionWebsocket.as_asgi(), name='executions-ws'),
]
