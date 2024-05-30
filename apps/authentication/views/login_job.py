# -*- coding: utf-8 -*-
#

from __future__ import unicode_literals
from django.views.generic.edit import FormView
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from users.utils import JobUtil
from common.utils import get_logger
from .. import forms, mixins, errors
from .utils import redirect_to_guard_view


logger = get_logger(__name__)
__all__ = ['UserSelectJobView']


get_job_method = None
try:
    get_job_method = import_string('data.login_job.main.get_job')
except Exception as e:
    logger.warning('Import get login_job method failed: {}, Maybe not enabled'.format(e))


class UserSelectJobView(mixins.CommonMixin, FormView):
    template_name = 'authentication/select_job.html'
    form_class = forms.UserSelectJobForm
    redirect_field_name = 'next'

    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except errors.SessionEmptyError:
            return redirect_to_guard_view('session_empty')

    def form_valid(self, form):
        job_id = form.cleaned_data['job_id']
        try:
            user = self.get_user_from_session()
            job_options = self.request.session.get('job_options', [])
            if list(filter(lambda j: j['id'] == job_id, job_options)):
                JobUtil(user.id).bind_job(job_id)
            else:
                form.add_error('job_id', _('Invalid choice: {}').format(job_id))
                return super().form_invalid(form)
        except errors.SessionEmptyError:
            return redirect_to_guard_view('session_empty')
        return redirect_to_guard_view('select_job_ok')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        options = []
        user = self.get_user_from_session()
        if callable(get_job_method):
            options = get_job_method(user)
        context.update({'job_options': options})
        self.request.session['job_options'] = options
        return context
