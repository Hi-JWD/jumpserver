import sqlparse

from typing import AnyStr, SupportsInt, Dict

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
from ..models import Plan, Playback, Environment, Command, Execution
from ..const import (
    PlanStrategy, FORMAT_COMMAND_CACHE_KEY, PAUSE_RE, CommandCategory,
    FILE_COMMAND_CACHE_KEY
)


class SimpleCommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Command
        fields = ['id', 'input', 'index']


class CommandSerializer(serializers.ModelSerializer):
    class Meta(SimpleCommandSerializer.Meta):
        fields = SimpleCommandSerializer.Meta.fields + [
            'output', 'status', 'timestamp'
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

    execution = ObjectRelatedField(read_only=True, attrs=('id', 'status'), label=_('Execution'))
    asset = ObjectRelatedField(queryset=Asset.objects, label=_('Asset'))
    account = ObjectRelatedField(queryset=Account.objects, label=_('Account'))
    playback = ObjectRelatedField(queryset=Playback.objects, label=_('Playback'))
    environment = ObjectRelatedField(queryset=Environment.objects, label=_('Environment'))
    strategy = LabeledChoiceField(choices=PlanStrategy.choices, label=_('Strategy'))
    status = serializers.SerializerMethodField(label=_('Status'))

    class Meta:
        model = Plan
        fields_mini = ['id', 'name', 'category']
        fields_small = fields_mini + [
            'environment', 'asset', 'account', 'playback', 'strategy'
        ]
        fields = fields_small + ['execution', 'status', 'comment']

    @staticmethod
    def get_status(obj):
        return Execution.objects.filter(plan_id=obj.id).values_list('status', flat=True)[0]

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

    def create_commands(self, instance, validated_data):
        token = self.context['request'].query_params.get('token')
        commands = cache.get(FORMAT_COMMAND_CACHE_KEY.format(token), [])
        with transaction.atomic():
            user = self.context['request'].user
            e = instance.create_execution(user)
            command_objs = []
            for i, c in enumerate(commands):
                command = Command(
                    execution_id=e.id, index=i, created_by=user,
                    updated_by=user, **self._format(c)
                )
                command_objs.append(command)
            commands = Command.objects.bulk_create(command_objs)
        return commands

    def bind_attr(self, validated_data):
        for field in self.bind_fields:
            if value := validated_data.pop(field, None):
                setattr(self, field, value)

    def create(self, validated_data):
        self.bind_attr(validated_data)
        instance = super().create(validated_data)
        self.create_commands(instance, validated_data)
        return instance

    def update(self, instance, validated_data):
        self.bind_attr(validated_data)
        self.create_commands(instance, validated_data)
        return super().update(instance, validated_data)


class FilePlanSerializer(PlanSerializer):
    bind_fields = ('mark_id',)

    mark_id = serializers.CharField(write_only=True, required=True, max_length=32, label=_('Mark ID'))

    class Meta(PlanSerializer.Meta):
        fields = PlanSerializer.Meta.fields + ['mark_id']

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

    def create_commands(self, instance, validated_data):
        commands = cache.get(FILE_COMMAND_CACHE_KEY.format(self.mark_id), [])
        with transaction.atomic():
            user = self.context['request'].user
            e = instance.create_execution(user)
            command_objs = []
            for c in commands:
                command = Command(
                    execution_id=e.id, index=c['index'], created_by=user,
                    updated_by=user, **self._format(c)
                )
                command_objs.append(command)
            commands = Command.objects.bulk_create(command_objs)
        return commands
