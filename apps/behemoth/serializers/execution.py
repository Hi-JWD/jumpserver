from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from common.serializers.fields import ObjectRelatedField

from ..models import Execution
from .. import const


class ExecutionSerializer(serializers.ModelSerializer):
    asset = ObjectRelatedField(read_only=True, attrs=('id', 'name', 'address'), label=_('Asset'))
    account = ObjectRelatedField(read_only=True, attrs=('id', 'name', 'username'), label=_('Account'))
    name = serializers.SerializerMethodField(label=_('Name'))
    status = serializers.ChoiceField(choices=const.TaskStatus)

    class Meta:
        model = Execution
        fields_mini = ['id', 'name', 'status']
        fields_small = fields_mini + ['date_updated', 'updated_by', 'created_by', 'reason']
        fields = fields_small + ['asset', 'account', 'playback_id']

    @staticmethod
    def get_name(obj):
        return obj.plan_meta.get('name', '')

    def validate(self, attrs):
        from behemoth.libs.pools.worker import worker_pool

        if (attrs['status'] == const.TaskStatus.success and
                self.instance.plan_meta['playback_strategy'] == const.PlaybackStrategy.auto):
            self.instance.playback_id = self.instance.plan_meta['playback_id']
            worker_pool.refresh_task_info(self.instance, 'success', '任务执行成功')
        return attrs


class ExecutionCommandSerializer(serializers.Serializer):
    command_id = serializers.UUIDField(required=True)
    status = serializers.ChoiceField(choices=const.CommandStatus)
    output = serializers.CharField(default='', allow_blank=True)
    timestamp = serializers.IntegerField(default=0)

    class Meta:
        fields = ['command_id', 'status', 'output', 'timestamp']
