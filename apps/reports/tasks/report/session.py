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
    NAME = '会话基础数据报表'
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
                'data': _('近 %s 天，共有 %s 人产生会话，其中用户 %s 使用最频繁，产生会话 %s 个，如下所示：') % (
                    self.time_period, self.session_user_count, max_user_name, max_user_count
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('用户名称'), _('连接数')], *user_session_info]
            }
        ]

    def _get_active_asset_data(self):
        asset_counter = self._session_data['asset_counter']
        max_asset_name, max_asset_count = self.get_info_from_counter(asset_counter)
        active_asset_info = [(asset, count) for asset, count in asset_counter.items()]
        return [
            {
                'type': c.TEXT,
                'data': _('近 %s 天内，共有 %s 个资产较为活跃，其中 %s 被连接 %s 次，如下所示：') % (
                    self.time_period, len(asset_counter.keys()), max_asset_name, max_asset_count
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('资产名称'), _('连接次数')], *active_asset_info]
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
                'data': _('近 %s 天内，连接资产协议有 %s 种，如下所示：') % (
                    self.time_period, len(protocol_counter.keys())
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('协议类型'), _('连接次数')], *protocol_session_data]
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
                'data': _('近 %s 天内，连接资产方式有 %s 种，如下所示：') % (
                    self.time_period, len(connect_counter.keys())
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('连接方式'), _('连接次数')], *connect_method_data]
            }
        ]

    def _get_session_duration_data(self):
        period_data = self._session_data['period_data']
        period_counter = period_data['period_counter']
        session_duration_info = [
            (_('%s-%s 小时') % (int(period), int(period) + 1), count)
            for period, count in period_counter.items()
        ]
        return [
            {
                'type': c.TEXT,
                'data': _('近 %s 天内，共产生会话 %s 个，其中最长 %s，最短为 %s，如下所示：') % (
                    self.time_period, sum(period_counter.values()),
                    period_data['max_period'], period_data['min_period']
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('时长范围'), _('连接次数')], *session_duration_info]
            }
        ]

    def get_pdf_data(self):
        return [
            {
                'title': '各用户会话数',
                'data': self._get_user_session_data()
            },
            {
                'title': '活跃资产数',
                'data': self._get_active_asset_data()
            },
            {
                'title': '各协议会话数',
                'data': self._get_protocol_of_session_data()
            },
            {
                'title': '各连接方式产生会话数',
                'data': self._get_connect_method_session_data()
            },
            {
                'title': '会话时长数',
                'data': self._get_session_duration_data()
            }
        ]

    def get_summary(self):
        summary = '''
        近 %s 天内，共产生会话 %s 个，连接会话人数 %s 人，
        单个会话时间最长 %s，最短 %s，上传文件 %s 次，下载文件 %s 次。
        ''' % (
            self.time_period, self.session_count, self.session_user_count,
            self.max_conn_time, self.min_conn_time, self.upload_count,
            self.download_count
        )
        return summary
