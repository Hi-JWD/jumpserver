from django.core.cache import cache
from rest_framework.request import Request

from rbac.models import Role, RoleBinding


class SpecialAuditMixin:
    request: Request
    filter_key: str

    @staticmethod
    def _get_role_users(role_name):
        cache_key = 'ROLE_%s_USERNAMES' % role_name.upper()
        usernames = cache.get(cache_key)
        if usernames is not None:
            return usernames

        role = Role.objects.filter(name=role_name).first()
        if not role:
            usernames = []
        else:
            users = RoleBinding.get_role_users(role).values('username', 'name')
            usernames = [f'{u["name"]}({u["username"]})' for u in users]
        cache.set(cache_key, usernames, timeout=10)
        return usernames

    def get_queryset(self):
        queryset = super().get_queryset()
        username = str(self.request.user)
        auditor_usernames = self._get_role_users('AuditorAdmin')
        sc_admin_usernames = self._get_role_users('AuthorizedAdmin')
        query_dict = {f'{self.filter_key}__in': auditor_usernames}
        if username in auditor_usernames:
            queryset = queryset.exclude(**query_dict)
        if username in sc_admin_usernames:
            queryset = queryset.filter(**query_dict)
        return queryset
