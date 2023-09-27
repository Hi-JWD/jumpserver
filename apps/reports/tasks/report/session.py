from collections import Counter
from datetime import datetime, timedelta

from django.utils.translation import gettext_lazy as _

from terminal.models import Session
from common.utils.timezone import format_seconds
from reports import const as c
from .common import BaseReport, register_report_template


SESSION_REPORT_DESCRIPTION = '''
统计各个组织下的会话总数，根据连接方式分组统计
'''


@register_report_template
class SessionReport(BaseReport):
    NAME = _('Session Basic Data Report')
    DESCRIPTION = SESSION_REPORT_DESCRIPTION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._time_ago = datetime.today().date() - timedelta(days=self.time_period)
        # summary 数据
        self.session_count = 0
        self.session_user_count = 0
        self.max_conn_time = ''
        self.min_conn_time = ''
        self.upload_count = 0
        self.download_count = 0
        # 放到最后，生成数据
        self._session_data = self._get_session_data()

    def _get_session_data(self):
        sessions = Session.objects.filter(date_end__gt=self._time_ago)
        user_counter, asset_counter = Counter(), Counter()
        connect_counter, protocol_counter = Counter(), Counter()
        period_counter = Counter()
        max_period, min_period = 0, 1000 * 24 * 3600
        for s in sessions:
            user_counter.update([s.user])
            asset_counter.update([s.asset])
            connect_counter.update([s.login_from_display])
            protocol_counter.update([s.protocol])
            time_period = s.date_end.timestamp() - s.date_start.timestamp()
            max_period = max(max_period, time_period)
            min_period = min(min_period, time_period)
            period_counter.update([time_period // 3600])
        self.session_count = sessions.count()
        self.max_conn_time = format_seconds(max_period)
        self.min_conn_time = format_seconds(min_period)
        return {
            'user_counter': user_counter, 'asset_counter': asset_counter,
            'connect_counter': connect_counter, 'protocol_counter': protocol_counter,
            'period_data': {
                'period_counter': period_counter,
                'max_period': self.max_conn_time, 'min_period': self.min_conn_time
            }
        }

    def _get_user_session_data(self):
        user_counter = self._session_data['user_counter']
        user_session_info = [(user, count) for user, count in user_counter.items()]
        max_user_name, max_user_count = self.get_info_from_counter(user_counter)
        self.session_user_count = len(user_counter.keys())
        return [
            {
                'type': c.TEXT,
                'data': _('In the past %s days, a total of %s people have generated sessions, '
                          'with user %s being the most frequently used and generating %s sessions, '
                          'as shown below:') % (
                    self.time_period, self.session_user_count, max_user_name, max_user_count
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('User display'), _('Connections')], *user_session_info]
            }
        ]

    def _get_active_asset_data(self):
        asset_counter = self._session_data['asset_counter']
        max_asset_name, max_asset_count = self.get_info_from_counter(asset_counter)
        active_asset_info = [(asset, count) for asset, count in asset_counter.items()]
        return [
            {
                'type': c.TEXT,
                'data': _('In the past %s days, a total of %s assets have been active, '
                          'of which %s have been connected %s times, as shown below:') % (
                    self.time_period, len(asset_counter.keys()), max_asset_name, max_asset_count
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('Asset display'), _('Connections')], *active_asset_info]
            }
        ]

    def _get_protocol_of_session_data(self):
        protocol_counter = self._session_data['protocol_counter']
        protocol_session_data = [
            (protocol, count) for protocol, count in protocol_counter.items()
        ]
        return [
            {
                'type': c.TEXT,
                'data': _('There are %s types of connection asset agreements '
                          'in the past %s days, as shown below:') % (
                    self.time_period, len(protocol_counter.keys())
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('Protocol'), _('Connections')], *protocol_session_data]
            }
        ]

    def _get_connect_method_session_data(self):
        connect_counter = self._session_data['connect_counter']
        connect_method_data = [
            (connect_type, count) for connect_type, count in connect_counter.items()
        ]
        return [
            {
                'type': c.TEXT,
                'data': _('There are %s ways to connect '
                          'assets in the past %s days, as follows:') % (
                    self.time_period, len(connect_counter.keys())
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('Connect method'), _('Connections')], *connect_method_data]
            }
        ]

    def _get_session_duration_data(self):
        period_data = self._session_data['period_data']
        period_counter = period_data['period_counter']
        session_duration_info = [
            (_('%s-%s hours') % (int(period), int(period) + 1), count)
            for period, count in period_counter.items()
        ]
        return [
            {
                'type': c.TEXT,
                'data': _('In the past %s days, a total of %s sessions have '
                          'been generated, with the longest being %s and the '
                          'shortest being %s, as shown below:') % (
                    self.time_period, sum(period_counter.values()),
                    period_data['max_period'], period_data['min_period']
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('Duration range'), _('Connections')], *session_duration_info]
            }
        ]

    def get_pdf_data(self):
        return [
            {
                'title': _('Number of sessions per user'),
                'data': self._get_user_session_data()
            },
            {
                'title': _('Number of active assets'),
                'data': self._get_active_asset_data()
            },
            {
                'title': _('Number of sessions per protocol'),
                'data': self._get_protocol_of_session_data()
            },
            {
                'title': _('Number of sessions per connection method'),
                'data': self._get_connect_method_session_data()
            },
            {
                'title': _('Session duration'),
                'data': self._get_session_duration_data()
            }
        ]

    def get_summary(self):
        summary = _('In the past %s days, a total of %s sessions '
                    'have been generated, with %s connected sessions. '
                    'The maximum duration of a single session is %s, '
                    'and the minimum duration is %s. Files have been '
                    'uploaded %s times and downloaded %s times.') % (
            self.time_period, self.session_count, self.session_user_count,
            self.max_conn_time, self.min_conn_time, self.upload_count,
            self.download_count
        )
        return summary
