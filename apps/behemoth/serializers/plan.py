from typing import AnyStr, Dict

from rest_framework import serializers
from django.utils.translation import gettext as _
from django.db import transaction
from django.core.cache import cache
from django.utils._os import safe_join
from django.conf import settings

from common.serializers.fields import ObjectRelatedField, LabeledChoiceField
from common.utils import lazyproperty
from assets.models import Asset
from accounts.models import Account
from behemoth.models import Plan, Playback, Environment, Command, Execution, SubPlan
from behemoth.const import (
    PlanStrategy, FORMAT_COMMAND_CACHE_KEY, PAUSE_RE, CommandCategory,
    FILE_COMMAND_CACHE_KEY, PlaybackStrategy
)


class SimpleCommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Command
        fields = ['id', 'input', 'index', 'category']


class UploadCommandSerializer(serializers.Serializer):
    ACTION_CHOICES = [
        ('cache_pause', 'cache_pause'),
        ('cache_file', 'cache_file')
    ]
    mark_id = serializers.CharField(required=True, max_length=32, label=_('Mark ID'))
    action = serializers.ChoiceField(choices=ACTION_CHOICES, label=_('Type'))
    index = serializers.CharField(required=False, max_length=32, label=_('Index'))


class SubPlanSerializer(serializers.ModelSerializer):
    execution = ObjectRelatedField(
        queryset=Execution.objects, attrs=('id', 'status'), label=_('Execution')
    )
    status = serializers.SerializerMethodField(label=_('Status'))
    task_id = serializers.SerializerMethodField(label=_('Task ID'))

    class Meta:
        model = SubPlan
        fields_mini = ['id', 'name', 'serial']
        fields = fields_mini + [
            'date_created', 'created_by', 'execution',
            'status', 'task_id'
        ]

    @staticmethod
    def get_status(obj):
        return obj.execution.status

    @staticmethod
    def get_task_id(obj):
        return obj.execution.task_id


class CommandSerializer(serializers.ModelSerializer):
    class Meta(SimpleCommandSerializer.Meta):
        fields = SimpleCommandSerializer.Meta.fields + [
            'output', 'status', 'timestamp', 'pause'
        ]

    @lazyproperty
    def filepath_prefix(self):
        return len(safe_join(settings.SHARE_DIR, 'command_upload_file')) + 22

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.category == CommandCategory.file:
            data['input'] = data['input'][self.filepath_prefix:]
        return data


class PlanSerializer(serializers.ModelSerializer):
    bind_fields = tuple()

    asset = ObjectRelatedField(queryset=Asset.objects, label=_('Asset'))
    account = ObjectRelatedField(queryset=Account.objects, label=_('Account'))
    playback = ObjectRelatedField(queryset=Playback.objects, label=_('Playback'))
    environment = ObjectRelatedField(queryset=Environment.objects, label=_('Environment'))
    plan_strategy = LabeledChoiceField(choices=PlanStrategy.choices, label=_('Plan strategy'))
    playback_strategy = LabeledChoiceField(choices=PlaybackStrategy.choices, label=_('Playback strategy'))

    class Meta:
        model = Plan
        fields_mini = ['id', 'name', 'category']
        fields_small = fields_mini + [
            'environment', 'asset', 'account', 'playback', 'plan_strategy', 'playback_strategy'
        ]
        fields = fields_small + [
            'created_by', 'comment', 'date_created'
        ]


class BaseSubPlanSerializer(serializers.ModelSerializer):
    bind_fields = ['token']

    name = serializers.CharField(required=False, label=_('Name'))
    token = serializers.CharField(write_only=True, max_length=16, label=_('Token'))

    class Meta:
        model = SubPlan
        fields_mini = ['id', 'name']
        fields = fields_mini + ['serial', 'created_by', 'date_created'] + ['token', 'plan']

    def bind_attr(self, validated_data):
        for field in self.bind_fields:
            if value := validated_data.pop(field, None):
                setattr(self, field, value)

    @staticmethod
    def _format(c: AnyStr) -> Dict:
        name, describe, pause = '', '', False
        match = PAUSE_RE.search(c)
        if match:
            name, describe = match.group(1), match.group(2)
            pause = match.group(3) == 'TRUE'
        if name and describe:
            input_, output = name, describe
            category = CommandCategory.pause
        else:
            input_, output = c, ''
            category = CommandCategory.command
        command = {
            'input': input_, 'output': output, 'category': category, 'pause': pause
        }
        return command

    def get_commands(self):
        return cache.get(FORMAT_COMMAND_CACHE_KEY.format(self.token), [])

    def create_commands(self, instance):
        commands = self.get_commands()
        with transaction.atomic():
            command_objs = []
            for i, c in enumerate(commands):
                command = Command(
                    execution_id=instance.execution.id, index=i, **self._format(c)
                )
                command_objs.append(command)
            commands = Command.objects.bulk_create(command_objs)
        return commands

    def create(self, validated_data):
        self.bind_attr(validated_data)
        instance = super().create(validated_data)
        self.create_commands(instance)
        return instance

    def update(self, instance, validated_data):
        self.bind_attr(validated_data)
        self.create_commands(instance)
        return super().update(instance, validated_data)


class SubPlanCommandSerializer(BaseSubPlanSerializer):
    class Meta(BaseSubPlanSerializer.Meta):
        fields = BaseSubPlanSerializer.Meta.fields


class SubPlanFileSerializer(BaseSubPlanSerializer):
    bind_fields = BaseSubPlanSerializer.bind_fields + ['mark_id']

    mark_id = serializers.CharField(write_only=True, required=True, max_length=32, label=_('Mark ID'))

    class Meta(BaseSubPlanSerializer.Meta):
        fields = BaseSubPlanSerializer.Meta.fields + [
            'mark_id'
        ]

    @staticmethod
    def _format(c: Dict) -> Dict:
        if c['category'] == CommandCategory.pause:
            input_, output, pause = c['name'], c['describe'], c['pause']
        else:
            input_, output, pause = c['filepath'], '', False
        return {
            'input': input_, 'output': output,
            'category': c['category'], 'pause': pause
        }

    def get_commands(self):
        return cache.get(FILE_COMMAND_CACHE_KEY.format(self.mark_id), [])


class SyncPlanSerializer(serializers.Serializer):
    pass
