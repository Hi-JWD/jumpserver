from behemoth.models import Worker
from .common import AssetSerializer

__all__ = ['WorkerSerializer']


class WorkerSerializer(AssetSerializer):
    class Meta(AssetSerializer.Meta):
        model = Worker
        fields = AssetSerializer.Meta.fields + ['base']
