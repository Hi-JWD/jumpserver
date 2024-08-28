import sqlparse

from typing import AnyStr, Dict

from rest_framework import serializers
from django.utils.translation import gettext as _
from django.db import transaction, models
from django.core.cache import cache
from django.conf import settings

from common.serializers.fields import ObjectRelatedField, LabeledChoiceField
from common.utils import random_string
from common.serializers import FileSerializer
from assets.models import Database
from accounts.models import Account
from behemoth.models import (
    Plan, Playback, Environment, Command, PlaybackExecution,
    Execution, ObjectExtend
)
from behemoth.libs.parser.handle import parse_sql as oracle_parser
from behemoth.const import (
    PlanStrategy, FORMAT_COMMAND_CACHE_KEY, PAUSE_RE, PlaybackStrategy,
    FormatType, PlanCategory, PLAN_TASK_ACTIVE_KEY, TaskStatus,
    ExecutionCategory,
)


class SimpleCommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Command
        fields = ['id', 'input', 'index']


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
            FormatType.line_break: lambda s: [c for c in s.split('\n') if c],
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


class CommandSerializer(SimpleCommandSerializer):
    status = serializers.ChoiceField(choices=TaskStatus.choices, label=_('Status'))

    class Meta(SimpleCommandSerializer.Meta):
        fields = SimpleCommandSerializer.Meta.fields + [
            'output', 'status', 'timestamp', 'pause'
        ]


class BasePlanSerializer(serializers.ModelSerializer):
    playback = ObjectRelatedField(queryset=Playback.objects, label=_('Monthly version'))
    environment = ObjectRelatedField(queryset=Environment.objects, label=_('Environment'))
    plan_strategy = LabeledChoiceField(choices=PlanStrategy.choices, label=_('Plan strategy'))
    category = LabeledChoiceField(required=False, choices=PlanCategory.choices, label=_('Category'))
    execution = serializers.SerializerMethodField(label=_('Execution'))

    class Meta:
        model = Plan
        fields_mini = ['id', 'name', 'category']
        fields_small = fields_mini + ['environment', 'playback', 'plan_strategy']
        fields = fields_small + ['execution', 'created_by', 'comment', 'date_created']

    @staticmethod
    def get_execution(obj):
        task_id, status = '', TaskStatus.not_start
        for e in obj.executions.values('status', 'task_id'):
            task_id = e['task_id']
            if e['status'] != TaskStatus.success:
                status = e['status']
                break
            else:
                status = e['status']
        return {'task_id': task_id, 'status': status}


class SyncPlanSerializer(BasePlanSerializer):
    users = serializers.SerializerMethodField(label=_('Users'))
    playback_executions = serializers.ListSerializer(
        child=serializers.CharField(max_length=36), label=_('Playback executions')
    )

    class Meta(BasePlanSerializer.Meta):
        fields = BasePlanSerializer.Meta.fields + ['users', 'playback_executions']

    @staticmethod
    def get_users(obj):
        ttl = cache.ttl(PLAN_TASK_ACTIVE_KEY.format(obj.id))
        users = cache.get(PLAN_TASK_ACTIVE_KEY.format(obj.id), [])
        participants = getattr(settings, 'SYNC_PLAN_REQUIRED_PARTICIPANTS', 2)
        wait_timeout = getattr(settings, 'SYNC_PLAN_WAIT_PARTICIPANT_IDLE', 3600)

        count = obj.executions.exclude(status=TaskStatus.success).count()
        if count != 0:
            return {
                'ttl': ttl, 'users': users,
                'wait_timeout': wait_timeout, 'participants': participants
            }
        else:
            return {'ttl': -1, 'users': []}

    def validate(self, attrs):
        attrs['category'] = PlanCategory.sync
        attrs = super().validate(attrs)
        return attrs

    @staticmethod
    def do_plan_other_action(plan, execution_ids):
        executions = PlaybackExecution.objects.filter(id__in=execution_ids)
        ObjectExtend.objects.create( # noqa
            obj_id=plan.id, category=Plan._meta.db_table, # noqa
            meta={'playback_executions': execution_ids}
        )
        # 遍历循环走SQL了吗？So crazy!
        for serial, item in enumerate(executions):
            asset_name = item.meta.get('asset', '')
            account_username = item.meta.get('account', '')
            execution = plan.create_execution(
                name=item.execution.name, asset_name=asset_name,
                account_username=account_username, category=item.execution.category,
                version=item.execution.version
            )
            command_objs, command_extra = [], []
            if execution.category == ExecutionCategory.pause:
                command_extra.append('output')
            commands = Command.objects.filter(execution_id=item.execution_id).order_by('index')
            for idx, command in enumerate(commands):
                command_objs.append(
                    Command(**command.to_dict(command_extra), index=idx, execution_id=execution.id)
                )
            Command.objects.bulk_create(command_objs)
            commands.filter(has_delete=True).delete()

    def update(self, instance, validated_data):
        execution_ids = validated_data.pop('playback_executions', None)
        plan = super().update(instance, validated_data)
        plan.executions.all().delete()
        self.do_plan_other_action(plan, execution_ids)
        return plan

    def create(self, validated_data):
        execution_ids = validated_data.pop('playback_executions', [])
        plan = super().create(validated_data)
        self.do_plan_other_action(plan, execution_ids)
        return plan


class DeployPlanSerializer(BasePlanSerializer):
    asset = ObjectRelatedField(
        queryset=Database.objects, attrs=('id', 'name', 'address', 'type'), label=_('Asset')
    )
    account = ObjectRelatedField(queryset=Account.objects, label=_('Account'))
    playback_strategy = LabeledChoiceField(
        choices=PlaybackStrategy.choices, label=_('Playback strategy')
    )
    c_type = LabeledChoiceField(choices=[], label=_('type'))

    class Meta(BasePlanSerializer.Meta):
        fields = BasePlanSerializer.Meta.fields + [
            'asset', 'account', 'playback_strategy', 'c_type'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choice_data = getattr(settings, 'DEPLOY_PLAN_CUSTOM_TYPE', [])
        has_default = bool(list(filter(lambda x: x['id'] == 'default', choice_data)))
        if not has_default:
            choice_data = [{'id': 'default', 'label': _('Default')}]
        choices = [(c['id'], c['label']) for c in choice_data]
        self.fields['c_type'].choices = choices

    def validate(self, attrs):
        attrs['category'] = PlanCategory.deploy
        attrs = super().validate(attrs)
        return attrs


class BaseCreateExecutionSerializer(serializers.ModelSerializer):
    bind_fields = ['token']

    name = serializers.CharField(required=False, allow_blank=True, label=_('Name'))
    token = serializers.CharField(write_only=True, max_length=16, label=_('Token'))

    class Meta:
        model = Execution
        fields_mini = ['id', 'name']
        fields_small = fields_mini + ['created_by', 'date_created']
        fields_fk = ['plan']
        fields = fields_small + fields_fk + ['token']

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
        else:
            input_, output = c, ''
        command = {
            'input': input_, 'output': output, 'pause': pause
        }
        return command

    def get_commands(self):
        return cache.get(FORMAT_COMMAND_CACHE_KEY.format(self.token), [])

    def create_commands(self, instance):
        commands = self.get_commands()
        with transaction.atomic():
            command_objs = []
            for i, c in enumerate(commands):
                command_objs.append(
                    Command(execution_id=instance.id, index=i, **self._format(c))
                )
            commands = Command.objects.bulk_create(command_objs)
        return commands

    def create(self, validated_data):
        self.bind_attr(validated_data)
        plan = validated_data['plan']
        validated_data.update({
            'asset': plan.asset, 'account': plan.account,
            'user_id': self.context['request'].user.id
        })
        instance = super().create(validated_data)
        self.create_commands(instance)
        return instance

    def update(self, instance, validated_data):
        self.bind_attr(validated_data)
        self.create_commands(instance)
        return super().update(instance, validated_data)


class CommandExecutionSerializer(BaseCreateExecutionSerializer):
    class Meta(BaseCreateExecutionSerializer.Meta):
        fields = BaseCreateExecutionSerializer.Meta.fields + ['version']


class SyncPlanUploadSerializer(FileSerializer):
    version = serializers.CharField(max_length=256, label=_('Version'))
    zip_entry_file = serializers.CharField(default='', max_length=256, label=_('Zip entry file'))
