from rest_framework import serializers

from ..models import Execution
from .. import const


class ExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields_mini = ['id', 'asset']
        fields_small = fields_mini
        fields = fields_small


class ExecutionStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=const.TaskStatus)

    class Meta:
        fields = ['status']


class ExecutionCommandSerializer(serializers.Serializer):
    command_id = serializers.UUIDField(required=True)
    status = serializers.BooleanField()
    result = serializers.CharField(default='')

    class Meta:
        fields = ['command_id', 'status', 'result']
