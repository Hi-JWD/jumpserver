from collections import defaultdict, OrderedDict

from django.utils import timezone
from django.http.response import JsonResponse
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.request import Request

from behemoth.models import Execution, Environment
from common.utils import lazyproperty
from orgs.utils import current_org
from orgs.caches import OrgResourceStatisticsCache
from common.utils.timezone import local_now, local_zero_hour


class DateTimeMixin:
    request: Request

    @property
    def org(self):
        return current_org

    @lazyproperty
    def days(self):
        query_params = self.request.query_params
        count = query_params.get('days')
        count = int(count) if count else 1
        return count

    @property
    def days_to_datetime(self):
        days = self.days
        if days == 1:
            t = local_zero_hour()
        else:
            t = local_now() - timezone.timedelta(days=days)
        return t

    @lazyproperty
    def date_start_end(self):
        return self.days_to_datetime.date(), local_now().date() + timezone.timedelta(days=1)

    @lazyproperty
    def dates_list(self):
        return [
            (local_now() - timezone.timedelta(days=i)).date()
            for i in range(self.days - 1, -1, -1)
        ]

    def get_dates_metrics_date(self):
        return [d.strftime('%m-%d') for d in self.dates_list] or ['0']


class IndexApi(DateTimeMixin, APIView):
    http_method_names = ['get']
    rbac_perms = {
        'GET': ['rbac.view_console'],
    }
    ENV_CACHE_KEY = 'behemoth:index:environment:{}:{}'

    @staticmethod
    def get_dates_top10_executions():
        executions = Execution.objects.values(
            'name', 'category', 'status', 'task_id', 'date_updated'
        ).order_by("-date_updated")
        return list(executions[:10])

    def get_date_metrics(self, queryset, field_name, count_field):
        queryset = queryset.filter(
            **{f'{field_name}__range': self.date_start_end}
        ).values_list(field_name, count_field)

        date_group_map = defaultdict(set)
        for datetime, count_field in queryset:
            date_str = str(datetime.date())
            date_group_map[date_str].add(count_field)

        return [
            len(date_group_map.get(str(d), set())) for d in self.dates_list
        ]

    def get_dates_metrics_total_count_active_executions_random(self):
        import random
        dates = self.get_dates_metrics_date()
        envs = []
        for env in Environment.objects.all():
            data = []
            for __ in dates:
                success, failed = random.randint(0, 100), random.randint(0, 10)
                data.append({'success': success, 'failed': failed})
            envs.append({'name': env.name, 'data': data})
        return {'date': dates, 'data': envs}

    def get_dates_metrics_total_count_active_executions(self):
        def _compute_timeout(current, days):
            hour = 3600
            if current == local_now().date():
                return hour
            return hour * 24 * (days - (local_now().date() - current).days)

        dates = self.get_dates_metrics_date()
        envs = []
        for env in Environment.objects.all():
            temp_data = OrderedDict({d: {'success': 0, 'failed': 0} for d in dates})
            for plan in env.plans.all():
                current_date, end_date = self.date_start_end
                while current_date <= end_date:
                    cache_key = self.ENV_CACHE_KEY.format(plan.id, current_date)
                    cache_result = cache.get(cache_key)
                    if cache_result is not None:
                        qs = cache_result
                    else:
                        qs = plan.executions.all()
                        qs = qs.filter(date_updated__range=(current_date, current_date + timezone.timedelta(days=1)))
                        qs = list(qs.filter(status__in=['success', 'failed']).values_list('date_updated', 'status'))
                        cache.set(cache_key, qs, _compute_timeout(current_date, self.days))
                    current_date += timezone.timedelta(days=1)
                    for datetime_obj, status in qs:
                        if not temp_data.get(datetime_obj.strftime('%m-%d'), None):
                            continue
                        temp_data[datetime_obj.strftime('%m-%d')][status] += 1
            envs.append({'name': env.name, 'data': list(temp_data.values())})
        return {'date': dates, 'data': envs}

    def get(self, request, *args, **kwargs):
        data = {}
        query_params = request.query_params
        caches = OrgResourceStatisticsCache(self.org)
        if query_params.get('total_count') or query_params.get('total_count_environment'):
            data.update({
                'total_count_environment': caches.environments_amount,
            })

        if query_params.get('total_count') or query_params.get('total_count_playbacks'):
            data.update({
                'total_count_playbacks': caches.playbacks_amount,
            })

        if query_params.get('total_count') or query_params.get('total_count_executions'):
            data.update({
                'total_count_executions': caches.executions_amount,
            })

        if query_params.get('total_count') or query_params.get('total_count_this_month_executions'):
            data.update({
                'total_count_this_month_executions': caches.this_month_executions_amount,
            })

        if query_params.get('total_count') or query_params.get('total_count_failed_executions'):
            data.update({
                'total_count_failed_executions': caches.failed_executions_amount,
            })

        if query_params.get('dates_metrics'):
            result = self.get_dates_metrics_total_count_active_executions()
            data['dates_metrics_total_count_active_executions'] = result
        if query_params.get('dates_top10_executions'):
            data.update({
                'dates_top10_executions': self.get_dates_top10_executions(),
            })
        return JsonResponse(data, status=200)
