from tickets.models import ApplyLoginAssetTicket
from .base import BaseHandler
from .service import ServiceAclClient


class Handler(BaseHandler):
    ticket: ApplyLoginAssetTicket

    def _on_step_approved(self, step):
        is_finished = super()._on_step_approved(step)
        if is_finished:
            self.ticket.activate_connection_token_if_need()
            meta = self.ticket.meta
            ServiceAclClient(
                meta.get('acl_id'), self.ticket.apply_login_user.username,
                self.ticket.apply_login_asset.id, self.ticket.apply_login_account
            ).decided_to_release(meta.get('valid_period'))
        return is_finished
