from django.utils.translation import gettext as _
from django.template.loader import render_to_string

from notifications.notifications import UserMessage


class BulkUpdatePlatformSkipAssetUserMsg(UserMessage):
    def __init__(self, user, assets):
        super().__init__(user)
        self.assets = assets

    def get_html_msg(self) -> dict:
        subject = _("Batch update platform in assets, skipping assets that do not meet platform type")
        message = f'<ol>{"".join([f"<li>{asset}</li>" for asset in self.assets])}</ol>'
        return {
            'subject': subject,
            'message': message
        }

    @classmethod
    def gen_test_msg(cls):
        from users.models import User
        from assets.models import Asset
        user = User.objects.first()
        assets = Asset.objects.all()[:10]
        return cls(user, assets)


class UnableConnectAssetUserMsg(UserMessage):
    def __init__(self, user, assets):
        """
        assets => {'org': ['asset_id',]}
        """
        super().__init__(user)
        self.assets = assets

    def get_html_msg(self) -> dict:
        subject = _("The following assets have connectivity problems, please check.")
        message = render_to_string('assets/unable_connect_asset.html', {'data': self.assets})
        return {
            'subject': subject,
            'message': message
        }
