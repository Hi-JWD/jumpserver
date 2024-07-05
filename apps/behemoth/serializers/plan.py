import sqlparse

from typing import AnyStr, Dict

from rest_framework import serializers
from django.utils.translation import gettext as _
from django.db import transaction
from django.core.cache import cache
from django.utils._os import safe_join
from django.conf import settings

from common.serializers.fields import ObjectRelatedField, LabeledChoiceField
from common.utils import lazyproperty, random_string
from assets.models import Database
from accounts.models import Account
from behemoth.models import (
    Plan, Playback, Environment, Command, Execution, SubPlan,
    SyncPlanCommandRelation
)
from behemoth.libs.parser.handle import parse_sql as oracle_parser
from behemoth.const import (
    PlanStrategy, FORMAT_COMMAND_CACHE_KEY, PAUSE_RE, CommandCategory,
    FILE_COMMAND_CACHE_KEY, PlaybackStrategy, FormatType, PlanCategory
)


class SimpleCommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Command
        fields = ['id', 'input', 'index', 'category']


class FormatCommandSerializer(serializers.Serializer):
    format_type = serializers.ChoiceField(choices=FormatType.choices)
    command = serializers.CharField(write_only=True, label=_("Command"), required=True)
    command_list = serializers.ListSerializer(
        read_only=True, child=serializers.CharField(), label=_("Commands")
    )
    token = serializers.CharField(read_only=True, max_length=16, label=_('Token'))

    @staticmethod
    def convert_commands_by_sqlparse(commands: AnyStr):
        statements = sqlparse.split(commands)
        format_query = {
            'keyword_case': 'upper', 'strip_comments': True,
            'use_space_around_operators': True, 'strip_whitespace': True
        }
        return [sqlparse.format(s, **format_query) for s in statements]

    def get_commands(self, attrs):
        func_map = {
            FormatType.line_break: lambda s: s.split(),
            FormatType.sql: self.convert_commands_by_sqlparse,
            FormatType.oracle: oracle_parser,
        }
        commands = func_map[attrs['format_type']](attrs['command'])
        cache.set(FORMAT_COMMAND_CACHE_KEY.format(attrs['token']), commands, 3600)
        return commands

    def validate(self, attrs):
        attrs = super().validate(attrs)
        attrs['token'] = random_string(16)
        attrs['command_list'] = self.get_commands(attrs)
        return attrs


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
            'status', 'task_id', 'plan_id'
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


class SyncPlanSerializer(serializers.ModelSerializer):
    _relation_map = {}

    asset = ObjectRelatedField(
        queryset=Database.objects, attrs=('id', 'name', 'address'), label=_('Asset')
    )
    account = ObjectRelatedField(queryset=Account.objects, label=_('Account'))
    playback = ObjectRelatedField(queryset=Playback.objects, label=_('Playback'))
    environment = ObjectRelatedField(queryset=Environment.objects, label=_('Environment'))
    plan_strategy = LabeledChoiceField(choices=PlanStrategy.choices, label=_('Plan strategy'))

    class Meta:
        model = Plan
        fields_mini = ['id', 'name', 'category']
        fields_small = fields_mini + [
            'environment', 'asset', 'account', 'playback', 'plan_strategy'
        ]
        fields = fields_small + [
            'created_by', 'comment', 'date_created'
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        attrs['category'] = PlanCategory.sync
        return attrs

    def get_or_create_relation(self, plan_name, plan):
        if obj := self._relation_map.get(plan_name):
            return obj
        obj = SyncPlanCommandRelation.objects.create(
            plan_name=plan_name, sync_plan=plan
        )
        self._relation_map[plan_name] = obj
        return obj

    def create(self, validated_data):
        plan = super().create(validated_data)
        execution_id = plan.create_sub_plan().execution.id
        executions = list(plan.playback.executions.values('execution_id', 'plan_name'))
        # 遍历循环走SQL了吗
        index = 0
        for item in executions:
            command_objs = []
            relation = self.get_or_create_relation(item['plan_name'], plan)
            commands = Command.objects.filter(execution_id=item['execution_id']).order_by('index')
            for command in commands:
                new_command = Command(
                    **command.to_dict(), relation_id=relation.id, index=index,
                    execution_id=execution_id
                )
                command_objs.append(new_command)
                index += 1
            Command.objects.bulk_create(command_objs)
        return plan


class DeployPlanSerializer(SyncPlanSerializer):
    playback_strategy = LabeledChoiceField(
        choices=PlaybackStrategy.choices, label=_('Playback strategy')
    )

    class Meta(SyncPlanSerializer.Meta):
        fields = SyncPlanSerializer.Meta.fields + ['playback_strategy']


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
