from behemoth.models import Worker
from assets.models import Asset
from assets.serializers import WorkerSerializer

from .asset import AssetViewSet


__all__ = ['WorkerViewSet']


class WorkerViewSet(AssetViewSet):
    model = Worker
    perm_model = Asset

    def get_serializer_classes(self):
        serializer_classes = super().get_serializer_classes()
        serializer_classes['default'] = WorkerSerializer
        return serializer_classes
