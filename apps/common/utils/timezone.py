from datetime import datetime, timedelta

from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.fields import DateTimeField


def as_current_tz(dt: datetime):
    return dt.astimezone(dj_timezone.get_current_timezone())


def utc_now():
    return dj_timezone.now()


def local_now():
    return dj_timezone.localtime(dj_timezone.now())


def local_now_display(fmt='%Y-%m-%d %H:%M:%S'):
    return local_now().strftime(fmt)


def local_now_date_display(fmt='%Y-%m-%d'):
    return local_now().strftime(fmt)


def local_zero_hour(fmt='%Y-%m-%d'):
    return datetime.strptime(local_now().strftime(fmt), fmt)


def local_monday():
    zero_hour_time = local_zero_hour()
    return zero_hour_time - timedelta(zero_hour_time.weekday())


def format_seconds(seconds):
    minutes = seconds // 60
    seconds %= 60
    hours = minutes // 60
    minutes %= 60
    days = hours // 24
    hours %= 24
    result = ''
    if days:
        result += _('%s 天 ') % int(days)
    if hours:
        result += _('%s 小时 ') % int(hours)
    if minutes:
        result += _('%s 分钟 ') % int(minutes)
    result += _('%s 秒') % int(seconds)
    return result.strip()


_rest_dt_field = DateTimeField()
dt_parser = _rest_dt_field.to_internal_value
dt_formatter = _rest_dt_field.to_representation
