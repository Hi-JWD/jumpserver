import sqlparse

from typing import AnyStr, SupportsInt, Dict

from rest_framework import serializers
from django.utils.translation import gettext as _
from django.db import transaction

from common.serializers.fields import ObjectRelatedField, LabeledChoiceField
from assets.models import Asset
from accounts.models import Account
from ..models import Plan, Playback, Environment, Command
from ..const import PlanStrategy, CommandCategory, PAUSE_RE


class SimpleCommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Command
        fields = ['id', 'input', 'index']


class CommandSerializer(serializers.ModelSerializer):
    class Meta(SimpleCommandSerializer.Meta):
        fields = SimpleCommandSerializer.Meta.fields + [
            'output', 'status', 'timestamp'
        ]


class PlanSerializer(serializers.ModelSerializer):
    commands = serializers.CharField(required=False, label=_('Commands'))
    execution = ObjectRelatedField(read_only=True, attrs=('id', 'status'), label=_('Execution'))
    asset = ObjectRelatedField(queryset=Asset.objects, label=_('Asset'))
    account = ObjectRelatedField(queryset=Account.objects, label=_('Account'))
    playback = ObjectRelatedField(queryset=Playback.objects, label=_('Playback'))
    environment = ObjectRelatedField(queryset=Environment.objects, label=_('Environment'))
    strategy = LabeledChoiceField(choices=PlanStrategy.choices, label=_('Strategy'))

    class Meta:
        model = Plan
        fields_mini = ['id', 'name', 'category']
        fields_small = fields_mini + [
            'environment', 'asset', 'account', 'playback', 'strategy'
        ]
        fields = fields_small + ['execution', 'commands', 'comment']

    @staticmethod
    def convert_commands(commands: AnyStr):
        statements = sqlparse.split(commands)
        format_query = {
            'keyword_case': 'upper', 'strip_comments': True,
            'use_space_around_operators': True, 'strip_whitespace': True
        }
        return [sqlparse.format(s, **format_query) for s in statements]

    @staticmethod
    def _format_command(c: AnyStr) -> Dict:
        match = PAUSE_RE.search(c)
        name, describe = match.group(1), match.group(2)
        pause = match.group(3) == 'TRUE'
        if name and describe:
            input_, output = name, describe
            category = CommandCategory.pause
        else:
            input_, output = c[0], ''
            category = CommandCategory.command
        command = {
            'input': input_, 'output': output, 'category': category, 'pause': pause
        }
        return command

    def create_commands(self, instance, commands: AnyStr):
        commands = self.convert_commands(commands)
        with transaction.atomic():
            user = self.context['request'].user
            execution = instance.create_execution(user)
            command_objs = []
            for i, c in enumerate(commands):
                command = Command(
                    execution_id=execution.id, index=i, created_by=user,
                    updated_by=user, **self._format_command(c)
                )
                command_objs.append(command)
            commands = Command.objects.bulk_create(command_objs)
        return commands

    def create(self, validated_data):
        commands = validated_data.pop('commands', [])
        instance = super().create(validated_data)
        self.create_commands(instance, commands)
        return instance

    def update(self, instance, validated_data):
        commands = validated_data.pop('commands', [])
        self.create_commands(instance, commands)
        return super().update(instance, validated_data)
