# -*- coding: utf-8 -*-
#
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.static import serve
from rest_framework import generics
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.utils import get_logger
from jumpserver.conf import Config
from common.permissions import OnlySuperUser
from orgs.models import Organization
from orgs.utils import tmp_to_org
from rbac.permissions import RBACPermission
from xpack.plugins.cloud.const import ProviderChoices
from xpack.plugins.cloud.providers.huaweicloud_private import Client
from xpack.plugins.cloud.models import Account, SyncInstanceTask
from .. import serializers
from ..models import Setting
from ..signals import category_setting_updated
from ..utils import get_interface_setting_or_default

logger = get_logger(__file__)


class SettingsApi(generics.RetrieveUpdateAPIView):
    permission_classes = (RBACPermission,)

    serializer_class_mapper = {
        'all': serializers.SettingsSerializer,
        'basic': serializers.BasicSettingSerializer,
        'terminal': serializers.TerminalSettingSerializer,
        'security': serializers.SecuritySettingSerializer,
        'security_auth': serializers.SecurityAuthSerializer,
        'security_basic': serializers.SecurityBasicSerializer,
        'security_session': serializers.SecuritySessionSerializer,
        'security_password': serializers.SecurityPasswordRuleSerializer,
        'security_login_limit': serializers.SecurityLoginLimitSerializer,
        'ldap': serializers.LDAPSettingSerializer,
        'email': serializers.EmailSettingSerializer,
        'email_content': serializers.EmailContentSettingSerializer,
        'wecom': serializers.WeComSettingSerializer,
        'dingtalk': serializers.DingTalkSettingSerializer,
        'feishu': serializers.FeiShuSettingSerializer,
        'lark': serializers.LarkSettingSerializer,
        'slack': serializers.SlackSettingSerializer,
        'auth': serializers.AuthSettingSerializer,
        'oidc': serializers.OIDCSettingSerializer,
        'keycloak': serializers.KeycloakSettingSerializer,
        'radius': serializers.RadiusSettingSerializer,
        'cas': serializers.CASSettingSerializer,
        'saml2': serializers.SAML2SettingSerializer,
        'oauth2': serializers.OAuth2SettingSerializer,
        'passkey': serializers.PasskeySettingSerializer,
        'clean': serializers.CleaningSerializer,
        'other': serializers.OtherSettingSerializer,
        'sms': serializers.SMSSettingSerializer,
        'alibaba': serializers.AlibabaSMSSettingSerializer,
        'tencent': serializers.TencentSMSSettingSerializer,
        'huawei': serializers.HuaweiSMSSettingSerializer,
        'cmpp2': serializers.CMPP2SMSSettingSerializer,
        'custom': serializers.CustomSMSSettingSerializer,
        'vault': serializers.VaultSettingSerializer,
        'chat': serializers.ChatAISettingSerializer,
        'announcement': serializers.AnnouncementSettingSerializer,
        'ticket': serializers.TicketSettingSerializer,
        'ops': serializers.OpsSettingSerializer,
        'virtualapp': serializers.VirtualAppSerializer,
        'cloud_setting': serializers.CloudSettingSerializer,
    }

    rbac_category_permissions = {
        'basic': 'settings.view_setting',
        'terminal': 'settings.change_terminal',
        'ops': 'settings.change_ops',
        'ticket': 'settings.change_ticket',
        'virtualapp': 'settings.change_virtualapp',
        'announcement': 'settings.change_announcement',
        'security': 'settings.change_security',
        'security_basic': 'settings.change_security',
        'security_auth': 'settings.change_security',
        'security_session': 'settings.change_security',
        'security_password': 'settings.change_security',
        'security_login_limit': 'settings.change_security',
        'ldap': 'settings.change_auth',
        'email': 'settings.change_email',
        'email_content': 'settings.change_email',
        'wecom': 'settings.change_auth',
        'dingtalk': 'settings.change_auth',
        'feishu': 'settings.change_auth',
        'auth': 'settings.change_auth',
        'oidc': 'settings.change_auth',
        'keycloak': 'settings.change_auth',
        'radius': 'settings.change_auth',
        'cas': 'settings.change_auth',
        'sso': 'settings.change_auth',
        'saml2': 'settings.change_auth',
        'oauth2': 'settings.change_auth',
        'clean': 'settings.change_clean',
        'other': 'settings.change_other',
        'sms': 'settings.change_sms',
        'alibaba': 'settings.change_sms',
        'tencent': 'settings.change_sms',
        'vault': 'settings.change_vault',
    }

    def get_queryset(self):
        return Setting.objects.all()

    def check_permissions(self, request):
        category = request.query_params.get('category', 'basic')
        perm_required = self.rbac_category_permissions.get(category)
        has = self.request.user.has_perm(perm_required)

        if not has:
            self.permission_denied(request)

    def get_serializer_class(self):
        category = self.request.query_params.get('category', 'basic')
        default = serializers.BasicSettingSerializer
        cls = self.serializer_class_mapper.get(category, default)
        return cls

    def get_fields(self):
        serializer = self.get_serializer_class()()
        fields = serializer.get_fields()
        return fields

    def get_object(self):
        items = self.get_fields().keys()
        obj = {}
        for item in items:
            if hasattr(settings, item):
                obj[item] = getattr(settings, item)
            else:
                obj[item] = Config.defaults[item]
        return obj

    def parse_serializer_data(self, serializer):
        data = []
        fields = self.get_fields()
        encrypted_items = [name for name, field in fields.items() if field.write_only]
        category = self.request.query_params.get('category', '')
        for name, value in serializer.validated_data.items():
            encrypted = name in encrypted_items
            if encrypted and value in ['', None]:
                continue
            data.append({
                'name': name, 'value': value,
                'encrypted': encrypted, 'category': category
            })
        return data

    def send_signal(self, serializer):
        category = self.request.query_params.get('category', '')
        category_setting_updated.send(sender=self.__class__, category=category, serializer=serializer)

    def perform_update(self, serializer):
        post_data_names = list(self.request.data.keys())
        settings_items = self.parse_serializer_data(serializer)
        serializer_data = getattr(serializer, 'data', {})

        for item in settings_items:
            if item['name'] not in post_data_names:
                continue
            changed, setting = Setting.update_or_create(**item)
            if not changed:
                continue
            serializer_data[setting.name] = setting.cleaned_value

        setattr(serializer, '_data', serializer_data)
        if hasattr(serializer, 'post_save'):
            serializer.post_save()
        self.send_signal(serializer)
        if self.request.query_params.get('category') == 'ldap':
            self.clean_ldap_user_dn_cache()

    @staticmethod
    def clean_ldap_user_dn_cache():
        del_count = cache.delete_pattern('django_auth_ldap.user_dn.*')
        logger.debug(f'clear LDAP user_dn_cache count={del_count}')


class SettingsLogoApi(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        size = request.GET.get('size', 'small')
        interface_data = get_interface_setting_or_default()
        if size == 'small':
            logo_path = interface_data['logo_logout']
        else:
            logo_path = interface_data['logo_index']

        if logo_path.startswith('/media/'):
            logo_path = logo_path.replace('/media/', '')
            document_root = settings.MEDIA_ROOT
        elif logo_path.startswith('/static/'):
            logo_path = logo_path.replace('/static/', '/')
            document_root = settings.STATIC_ROOT
        else:
            return HttpResponse(status=status.HTTP_404_NOT_FOUND)
        return serve(request, logo_path, document_root=document_root)


class SyncOrgsApi(generics.ListCreateAPIView):
    permission_classes = (OnlySuperUser,)
    serializer_class = serializers.CloudRegionsSerializer

    @staticmethod
    def _get_client_attrs():
        return {
            'api_endpoint': settings.GLOBAL_HW_API_ENDPOINT,
            'sc_username': settings.GLOBAL_HW_SC_USERNAME,
            'sc_password': settings.GLOBAL_HW_SC_PASSWORD,
            'domain_name': settings.GLOBAL_HW_SC_DOMAIN
        }

    def list(self, request, *args, **kwargs):
        client = Client(**self._get_client_attrs())
        regions = client.describe_regions()
        return Response([{'id': r['id'], 'name': r['name']} for r in regions])

    def get_vdc_name(self, vdc_id, vdc_map):
        vdc = vdc_map.get(vdc_id)
        upper_id = vdc.get('upper_vdc_id')
        if upper_id != '0':
            upper_names = self.get_vdc_name(upper_id, vdc_map)
            upper_names.append(vdc)
            return upper_names
        else:
            return [vdc]

    def _get_resole_vdcs(self, vdcs):
        vdc_map = {v['id']: v for v in vdcs}
        result = [self.get_vdc_name(v['id'], vdc_map) for v in vdcs]
        return result

    def _create_org(self, vdc):
        account_name, task_name = 'Auto-Account', 'Auto-Task'
        org, __ = Organization.objects.get_or_create(
            name=vdc['name'], defaults={'builtin': True}
        )
        with tmp_to_org(org):
            account, __ = Account.objects.get_or_create(
                name=account_name, defaults={
                    'provider': ProviderChoices.huaweicloud_private,
                    'attrs': self._get_client_attrs()
                }
            )
            SyncInstanceTask.objects.get_or_create(
                name=task_name, defaults={
                    'account': account, 'is_periodic': True, 'interval': 1,
                    'regions': [{'id': vdc['region_id'], 'vdcs': [vdc['id']]}],
                }
            )

    def perform_create(self, serializer):
        client = Client(**self._get_client_attrs())
        for region in serializer.validated_data['regions']:
            for vdc in self._get_resole_vdcs(client.describe_vdcs(region)):
                if len(vdc) != 2:
                    continue
                self._create_org(vdc[1])
