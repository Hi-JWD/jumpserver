# ~*~ coding: utf-8 ~*~
import abc
import datetime

from django.utils import timezone
from django.db.models import Manager

from common.utils.common import pretty_string, get_logger
from behemoth.models import Command, Instruction


logger = get_logger(__name__)


class BaseStore(object):
    model: Manager

    def __init__(self, *args, **kwargs):
        pass

    @abc.abstractmethod
    def _get_obj(self, obj_params):
        pass

    @staticmethod
    def make_filter_kwargs(date_from=None, date_to=None, **query):
        filter_kwargs = {}
        without_timestamp = query.pop('without_timestamp', False)
        if not without_timestamp:
            date_from_default = timezone.now() - datetime.timedelta(days=7)
            date_to_default = timezone.now()

            date_from = date_from or date_from_default
            date_to = date_to or date_to_default
            if isinstance(date_from, datetime.datetime):
                date_from = date_from.timestamp()
            filter_kwargs['timestamp__gte'] = int(date_from)

            if isinstance(date_to, datetime.datetime):
                date_to = date_to.timestamp()
            filter_kwargs['timestamp__lte'] = int(date_to)

        key_reverse = {'input': 'input_icontains', 'output': 'output_icontains'}
        for key, value in query.items():
            new_key = key_reverse.get(key, key)
            filter_kwargs[new_key] = value
        return filter_kwargs

    def filter(
            self, date_from=None, date_to=None, **query
    ):
        filter_kwargs = self.make_filter_kwargs(
            date_from=date_from, date_to=date_to, **query
        )
        queryset = self.model.objects.filter(**filter_kwargs)
        return queryset

    def count(
            self, date_from=None, date_to=None, **query
    ):
        filter_kwargs = self.make_filter_kwargs(
            date_from=date_from, date_to=date_to, **query
        )
        count = self.model.objects.filter(**filter_kwargs).count()
        return count

    def save(self, command):
        self._get_obj(command).save()

    def bulk_save(self, commands):
        _commands = [self._get_obj(c) for c in commands]
        try:
            self.model.objects.bulk_create(_commands)
        except Exception as e:
            logger.error('Bulk save commands failed: {}'.format(e))
            return False
        return True


class CommandStore(BaseStore):
    model = Command

    def _get_obj(self, obj_params):
        cmd_input = pretty_string(obj_params['input'])
        cmd_output = pretty_string(obj_params['output'], max_length=1024)
        return self.model(
            input=cmd_input, output=cmd_output,
            org_id=obj_params['org_id'], task_id=obj_params['task_id'],
        )


class InstructionStore(BaseStore):
    model = Instruction

    def _get_obj(self, obj_params):
        cmd_input = pretty_string(obj_params['content'])
        return self.model(
            content=cmd_input, plan_id=obj_params['plan_id'],
            org_id=obj_params['org_id'],
        )
