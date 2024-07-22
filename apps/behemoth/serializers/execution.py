from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from common.serializers.fields import ObjectRelatedField

from ..models import Execution, PlaybackExecution
from .. import const


class ExecutionSerializer(serializers.ModelSerializer):
    asset = ObjectRelatedField(read_only=True, attrs=('id', 'name', 'address'), label=_('Asset'))
    account = ObjectRelatedField(read_only=True, attrs=('id', 'name', 'username'), label=_('Account'))
    status = serializers.ChoiceField(choices=const.TaskStatus)

    class Meta:
        model = Execution
        fields_mini = ['id', 'name', 'status']
        fields_small = fields_mini + ['date_created', 'updated_by', 'created_by', 'reason']
        fields = fields_small + ['asset', 'account', 'task_id']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not self.instance:
            return attrs

        from behemoth.libs.pools.worker import worker_pool

        if (attrs['status'] == const.TaskStatus.success and
                self.instance.plan.playback_strategy == const.PlaybackStrategy.auto):
            meta = {
                'asset': self.instance.asset.name, 'account': self.instance.account.username
            }
            PlaybackExecution.objects.create(
                execution=self.instance, plan_name=self.instance.plan.name,
                meta=meta, playback=self.instance.plan.playback,
            )
            worker_pool.record(self.instance, '命令执行完成', 'green')
        elif attrs['status'] == const.TaskStatus.failed:
            worker_pool.record(self.instance, '任务执行失败', 'red')
        return attrs


class ExecutionCommandSerializer(serializers.Serializer):
    command_id = serializers.UUIDField(required=True)
    status = serializers.ChoiceField(choices=const.CommandStatus)
    output = serializers.CharField(default='', allow_blank=True)
    timestamp = serializers.IntegerField(default=0)

    class Meta:
        fields = ['command_id', 'status', 'output', 'timestamp']
