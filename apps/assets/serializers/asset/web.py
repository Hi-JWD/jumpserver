from assets.models import Web
from .common import AssetSerializer, SpecialRoleAssetMixin

__all__ = ['WebSerializer']


class WebSerializer(SpecialRoleAssetMixin, AssetSerializer):
    class Meta(AssetSerializer.Meta):
        model = Web
        fields = AssetSerializer.Meta.fields + [
            'autofill', 'username_selector',
            'password_selector', 'submit_selector',
            'script'
        ]
        extra_kwargs = {
            **AssetSerializer.Meta.extra_kwargs,
            'address': {
                'label': 'URL'
            },
            'username_selector': {
                'default': 'name=username'
            },
            'password_selector': {
                'default': 'name=password'
            },
            'submit_selector': {
                'default': 'id=login_button',
            },
        }
