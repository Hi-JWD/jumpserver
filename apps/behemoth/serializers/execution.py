from rest_framework import serializers

from ..models import Execution


class ExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields_mini = ['id', 'asset']
        fields_small = fields_mini
        fields = fields_small
