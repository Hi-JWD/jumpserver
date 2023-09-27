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
    NAME = _('User Basic Data Report')
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
            user_source_counter.update([user.get_source_display()])

        self.user_source = '，'.join(_('%s: %s') % (k, v) for k, v in user_source_counter.items())
        data = [
            {
                'type': c.TEXT,
                'data': _('There are currently %s user groups, '
                          'with the highest number of users within '
                          'the group being %s, as shown below:') % (
                    len(user_groups), max_user['name']
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [
                    [_('User group'), _('Number of users per user group'), _('Organization')],
                    *user_groups_info
                ],
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
                role.display_name, role.get_scope_display(), user_amount,
                _('Yes') if role.builtin else _('No')
            ))
            if user_amount > max_role['count']:
                max_role = {
                    'name': role.display_name, 'count': user_amount
                }
        return [
            {
                'type': c.TEXT,
                'data': _('There are currently %s types of roles, '
                          'with %s maximum of %s people, as follows:') % (
                    len(roles), max_role['name'], max_role['count']
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [[_('Role display'), _('Role'), _('Users amount'), _('Is builtin')], *role_info],
                'params': {'label_index': 0, 'rank_index': 3}
            }
        ]

    @tmp_to_root_org()
    def _get_user_active_data(self, limit=10):
        sessions = Session.objects.values('user_id', 'org_id', 'user') \
                       .annotate(total=Count('user_id')) \
                       .annotate(last=Max('date_start')).order_by('-total')[:limit]

        users_info, total_login = [], 0
        for session in sessions:
            users_info.append((
                session['user'], session['total'], Organization.get_instance(session['org_id'])
            ))
            total_login += session['total']
        return [
            {
                'type': c.TEXT,
                'data': _('In the past %s days, logged in %s times '
                          'with %s people, as shown below:') % (
                    self.time_period, total_login, len(sessions)
                )
            },
            {
                'type': c.TABLE_BAR,
                'data': [
                    [_('User display'), _('Number of logins'), _('Organization')],
                    *users_info
                ],
            }
        ]

    def get_pdf_data(self):
        return [
            {
                'title': _('Number of users per user group'),
                'data': self._get_user_group_data()
            },
            {
                'title': _('Number of users in each role'),
                'data': self._get_user_role_data()
            },
            {
                'title': 'Number of user logins (Top 10)',
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
        summary = _('There are currently %s user groups and %s users, '
                    'including %s valid users and %s disabled users. '
                    'User sources are %s, %s system administrators, '
                    '%s organizational administrators, and %s other users. '
                    '%s new users have been added in the past %s, '
                    'and users have logged in %s times, successfully '
                    '%s times, and failed %s times.') % (
            self.user_group_count, self.user_count, self.valid_user_count,
            self.disabled_user_count, self.user_source, self.system_admin_count,
            self.org_admin_count, self.other_user_count, self.time_period,
            self.new_user_count, self.login_count, self.login_success_count,
            self.login_failed_count
        )
        return summary
