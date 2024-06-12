from rest_framework import serializers
from django.utils.translation import gettext as _
from django.db import transaction

from common.serializers.fields import ObjectRelatedField, LabeledChoiceField
from assets.models import Asset
from accounts.models import Account
from ..models import Plan, Playback, Environment, Command
from ..const import PlanStrategy


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
    def __convert_mysql(raw_commands):
        anno_symbol = '--'
        real_commands, temp_command, anno = [], [], ''
        commands = map(lambda c: c.strip(), raw_commands.split('\n'))
        for command in commands:
            if command.startswith(anno_symbol):
                anno = command
                continue

            temp_command.append(command)
            if ';' in command:
                real_commands.append((' '.join(temp_command).strip(), anno))
                temp_command.clear()
        return real_commands

    def convert_commands(self, platform, commands):
        real_commands = []
        if platform == 'mysql':
            real_commands = self.__convert_mysql(commands)
        return real_commands

    def create_commands(self, instance, commands):
        commands = self.convert_commands(instance.asset.type, commands)
        with transaction.atomic():
            user = self.context['request'].user
            execution = instance.create_execution(user)
            command_objs = [
                Command(
                    input=c[0], execution_id=execution.id, index=i,
                    created_by=user, updated_by=user
                ) for i, c in enumerate(commands)
            ]
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
