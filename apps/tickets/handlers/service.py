from tickets.const import TicketType


class ServiceClient(object):
    def __init__(self, ticket):
        self.ticket_info = self.obj_to_dict(ticket)

    @staticmethod
    def obj_to_dict(ticket):
        if ticket.status != 'open':
            return {}

        info = {
            'title': ticket.title,
            'assignees': [u.username for u in ticket.current_assignees],
            'comment': ticket.comment, 'applicant': ticket.applicant,
        }
        if ticket.type == TicketType.apply_asset:
            assets = []
            for item in ticket.apply_accounts_display:
                assets.append({'asset_name': item['asset'], 'accounts': item['accounts']})
            info.update({
                'assets': assets, 'apply_date_start': ticket.apply_date_start,
                'apply_date_expired': ticket.apply_date_expired,
            })
        elif ticket.type == TicketType.login_confirm:
            info.update({
                'apply_login_city': ticket.apply_login_city,
                'apply_login_datetime': ticket.apply_login_datetime,
                'apply_login_ip': ticket.apply_login_ip,
            })
        elif ticket.type == TicketType.command_confirm:
            info.update({
                'apply_from_cmd_filter_acl': ticket.apply_from_cmd_filter_acl,
                'apply_run_asset': ticket.apply_run_asset,
                'apply_run_account': ticket.apply_run_account,
                'apply_run_command': ticket.apply_run_command,
                'apply_run_user': ticket.apply_run_user,
            })
        elif ticket.type == TicketType.login_asset_confirm:
            info.update({
                'apply_login_asset': ticket.apply_login_asset,
                'apply_login_user': ticket.apply_login_user,
            })
        return info

    def request_ticket(self):
        print(self.ticket_info)
