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
    reason = serializers.CharField()

    class Meta:
        fields = ['status', 'reason']


class ExecutionCommandSerializer(serializers.Serializer):
    command_id = serializers.UUIDField(required=True)
    status = serializers.ChoiceField(choices=const.CommandStatus)
    result = serializers.CharField(default='')
    timestamp = serializers.IntegerField(default=0)

    class Meta:
        fields = ['command_id', 'status', 'result', 'timestamp']
