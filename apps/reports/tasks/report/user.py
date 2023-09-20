from collections import Counter

from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Max, Case, When

from audits.models import UserLoginLog
from terminal.models import Session
from rbac.models import Role, RoleBinding
from users.models import User, UserGroup
from orgs.models import Organization
from orgs.utils import tmp_to_root_org
from common.utils.timezone import local_now
from reports import const as c

from .common import BaseReport, register_report_template


USER_REPORT_DESCRIPTION = """
各用户组用户数
各角色用户数
用户登录次数 (Top 10)
"""


@register_report_template
class UserReport(BaseReport):
    NAME = '用户基础数据报表'
    DESCRIPTION = USER_REPORT_DESCRIPTION

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # summary 使用
        self.user_count = 0
        self.user_group_count = 0
        self.valid_user_count = 0
        self.disabled_user_count = 0
        self.user_source = ''
        self.system_admin_count = 0
        self.org_admin_count = 0
        self.other_user_count = 0
        self.new_user_count = 0
        self.login_count = 0
        self.login_success_count = 0
        self.login_failed_count = 0

    @tmp_to_root_org()
    def _get_user_group_data(self):
        users = User.objects.filter(is_service_account=False)
        user_groups = UserGroup.objects.all()

        self.user_group_count = len(user_groups)
        user_groups_info, max_user = [], {'name': '', 'count': 0}
        for user_group in user_groups:
            users_amount = user_group.users_amount
            user_groups_info.append((
                user_group.name, users_amount, user_group.org_name,
            ))
            if users_amount > max_user['count']:
                max_user = {
                    'name': f"{user_group.name}({user_group.org_name})", 'count': users_amount
                }

        self.user_count = len(users)
        user_source_counter = Counter()
        for user in users:
            if user.is_valid:
                self.valid_user_count += 1
            elif not user.is_active:
                self.disabled_user_count += 1

            if (local_now() - user.date_joined).days < self.time_period:
                self.new_user_count += 1
            user_source_counter.update([user.source])

        self.user_source = '，'.join(_('%s: %s 个') % (k, v) for k, v in user_source_counter.items())
        data = [
            {
                'type': c.TEXT,
                'data': _('当前共有用户组 %s 个, 组内用户最多的为 %s，如下所示：') % (
                    len(user_groups), max_user['name']
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('用户组名'), _('用户组用户个数'), _('组织名')], *user_groups_info]
            },
        ]
        return data

    def _get_user_role_data(self):
        roles = Role.objects.exclude(name='SystemComponent')
        role_info, max_role = [], {'name': '', 'count': 0}
        for role in roles:
            user_amount = RoleBinding.get_role_users(role).count()
            if role.is_system_admin():
                self.system_admin_count += user_amount
            elif role.is_org_admin():
                self.org_admin_count += user_amount
            else:
                self.other_user_count += user_amount
            role_info.append((
                role.name, role.scope, role.builtin, user_amount
            ))
            if user_amount > max_role['count']:
                max_role = {
                    'name': role.name, 'count': user_amount
                }
        return [
            {
                'type': c.TEXT,
                'data': _('当前共有 %s 类角色，其中 %s 最多为 %s 人，如下所示：') % (
                    len(roles), max_role['name'], max_role['count']
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('角色名称'), _('角色'), _('是否内置'), _('用户数量')], *role_info]
            }
        ]

    @tmp_to_root_org()
    def _get_user_active_data(self, limit=10):
        sessions = Session.objects.values('user_id', 'org_id', 'user') \
                       .annotate(total=Count('user_id')) \
                       .annotate(last=Max('date_start')).order_by('-total')[:limit]

        users_info, total_login = [], 0
        for rank, session in enumerate(sessions, 1):
            users_info.append((
                rank, session['user'], session['total'], Organization.get_instance(session['org_id'])
            ))
            total_login += session['total']
        return [
            {
                'type': c.TEXT,
                'data': _('近 %s 天内，登录 %s 次, 登录人数 %s 人，如下所示：') % (
                    self.time_period, total_login, len(sessions)
                )
            },
            {
                'type': c.TABLE,
                'data': [[_('排名'), _('用户名'), _('登录次数'), _('组织')], *users_info]
            }
        ]

    def get_pdf_data(self):
        return [
            {
                'title': '各用户组用户数',
                'data': self._get_user_group_data()
            },
            {
                'title': '各角色用户数',
                'data': self._get_user_role_data()
            },
            {
                'title': '用户登录次数 (Top 10)',
                'data': self._get_user_active_data()
            },
        ]

    @tmp_to_root_org()
    def _get_other_data(self):
        status_counts = UserLoginLog.objects.aggregate(
            success_count=Count(Case(When(status=True, then=1))),
            failed_count=Count(Case(When(status=False, then=1)))
        )
        self.login_success_count = status_counts['success_count']
        self.login_failed_count = status_counts['failed_count']
        self.login_count = self.login_success_count + self.login_failed_count

    def get_summary(self):
        self._get_other_data()
        summary = '''
        当前共有用户组 %s 个，用户 %s 个， 其中有效用户 %s 个，禁用用户 %s 个，
        用户来源: %s, 系统管理员 %s 个，组织管理员 %s 个，其他用户 %s 个。
        近 %s 内新增用户 %s 个， 用户产生登录行为 %s 次，成功 %s 次，失败 %s 次。
        ''' % (
            self.user_group_count, self.user_count, self.valid_user_count,
            self.disabled_user_count, self.user_source, self.system_admin_count,
            self.org_admin_count, self.other_user_count, self.time_period,
            self.new_user_count, self.login_count, self.login_success_count,
            self.login_failed_count
        )
        return summary
