from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from common.serializers.fields import ObjectRelatedField, LabeledChoiceField

from ..models import Execution, PlaybackExecution, Plan
from .. import const


class SimpleExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = ('id', 'status', 'task_id')


class ExecutionSerializer(serializers.ModelSerializer):
    asset = ObjectRelatedField(read_only=True, attrs=('id', 'name', 'address'), label=_('Asset'))
    account = ObjectRelatedField(read_only=True, attrs=('id', 'name', 'username'), label=_('Account'))
    status = serializers.ChoiceField(choices=const.TaskStatus)
    category = LabeledChoiceField(choices=const.ExecutionCategory.choices, label=_("Category"))

    class Meta:
        model = Execution
        fields_mini = ['id', 'name', 'status']
        fields_small = fields_mini + ['category', 'date_created', 'updated_by', 'created_by', 'reason']
        fields = fields_small + ['asset', 'account', 'task_id']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not self.instance:
            return attrs

        from behemoth.libs.pools.worker import worker_pool

        if attrs['status'] == const.TaskStatus.success:
            if self.instance.plan.playback_strategy == const.PlaybackStrategy.auto and \
                    self.instance.plan.category == const.PlanCategory.deploy:
                asset_name = self.instance.asset.name.split('-', 1)[-1]
                meta = {
                    'asset': asset_name, 'account': self.instance.account.username,
                    'plan_version': self.instance.plan.version,
                }
                PlaybackExecution.objects.create(
                    execution=self.instance, plan_name=self.instance.plan.name,
                    meta=meta, playback=self.instance.plan.playback,
                )
            worker_pool.record(self.instance, _('Command execution completed'), 'green')
        elif attrs['status'] == const.TaskStatus.failed:
            msg = f'{_("Task execution failed")}: {attrs["reason"]}'
            worker_pool.record(self.instance, msg, 'red')
        worker_pool.mark_task_status(self.instance.id, attrs['status'])
        return attrs


class ExecutionCommandSerializer(serializers.Serializer):
    command_id = serializers.UUIDField(required=True)
    status = serializers.ChoiceField(choices=const.CommandStatus)
    output = serializers.CharField(default='', allow_blank=True)
    timestamp = serializers.IntegerField(default=0)

    class Meta:
        fields = ['command_id', 'status', 'output', 'timestamp']
