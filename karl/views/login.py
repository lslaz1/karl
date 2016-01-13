# Copyright (C) 2008-2009 Open Society Institute
#               Thomas Moroz: tmoroz@sorosny.org
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License Version 2 as published
# by the Free Software Foundation.  You may not use, modify or distribute
# this program under any other version of the GNU General Public License.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import logging

import html2text

import copy
from datetime import datetime
from HTMLParser import HTMLParser
from urlparse import urljoin
import re
import requests

from pyramid.httpexceptions import HTTPFound
from pyramid.renderers import render_to_response
from pyramid.security import forget
from pyramid.security import remember
from pyramid.url import resource_url
from pyramid.exceptions import NotFound

from karl.application import is_normal_mode
from karl.utils import asbool
from karl.utils import find_profiles
from karl.utils import find_site
from karl.utils import find_users
from karl.utils import get_setting
from karl.utils import get_config_setting
from karl.utils import SafeDict
from karl.models.interfaces import ICatalogSearch
from karl.models.interfaces import IProfile
from karl import events
from karl.lockout import LockoutManager
from karl.registration import get_access_request_fields
from karl.twofactor import TwoFactor

from karl.views.api import TemplateAPI

from zope.component import getUtility
from zope.event import notify
from repoze.sendmail.interfaces import IMailDelivery
from repoze.postoffice.message import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'[^@]+@[^@]+\.[^@]+')


def _fixup_came_from(request, came_from):
    came_from = urljoin(request.application_url, came_from)
    if came_from.endswith('login.html'):
        came_from = came_from[:-len('login.html')]
    elif came_from.endswith('logout.html'):
        came_from = came_from[:-len('logout.html')]
    return came_from


class LoginView(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.settings = request.registry.settings
        came_from = request.session.get('came_from', request.url)
        came_from = _fixup_came_from(request, came_from)
        request.session['came_from'] = came_from
        self.came_from = came_from

    def login_locked_out(self, login):
        users = find_users(self.context)
        user = users and users.get(login=login)
        if not user:
            return False

        mng = LockoutManager(self.context, login)
        return mng.maxed_number_of_attempts()

    def login(self):
        context = self.context
        request = self.request
        # identify
        login = request.POST.get('login')
        password = request.POST.get('password')

        if self.login_locked_out(login):
            redirect = request.resource_url(
                request.root, 'login.html', query={
                    'reason': 'User locked out. Too many failed login attempts.'})
            return HTTPFound(location=redirect)

        notify(events.LoginAttempt(context, request, login, password))

        if login is None or password is None:
            return HTTPFound(location='%s/login.html' % request.application_url)
        max_age = request.POST.get('max_age')
        if max_age is not None:
            max_age = int(max_age)

        # authenticate
        userid = None
        reason = 'Bad username or password'
        users = find_users(context)
        for authenticate in (password_authenticator, impersonate_authenticator):
            userid = authenticate(context, users, login, password)
            if userid:
                break

        # if not successful, try again
        if not userid:
            notify(events.LoginFailed(context, request, login, password))
            redirect = request.resource_url(
                request.root, 'login.html', query={'reason': reason})
            return HTTPFound(location=redirect)

        tf = TwoFactor(context, request)

        if tf.enabled:
            code = request.POST.get('code')
            if not code:
                redirect = request.resource_url(
                    request.root, 'login.html',
                    query={'reason': 'No authentication code provided'})
                notify(events.LoginFailed(context, request, login, password))
                return HTTPFound(location=redirect)
            if tf.validate(userid, code):  # noqa
                notify(events.LoginFailed(context, request, login, password))
                redirect = request.resource_url(
                    request.root, 'login.html', query={'reason': 'Invalid authorization code'})  # noqa
                return HTTPFound(location=redirect)

        # else, remember
        notify(events.LoginSuccess(context, request, login, password))
        return remember_login(context, request, userid, max_age)

    def __call__(self):
        if self.request.params.get('form.submitted', None) is not None:
            resp = self.login()
            if resp:
                # if this returned with something, we deal with it
                return resp

        # Log in user seamlessly with kerberos if enabled
        try_kerberos = self.request.GET.get('try_kerberos', None)
        if try_kerberos:
            try_kerberos = asbool(try_kerberos)
        else:
            try_kerberos = asbool(get_config_setting('kerberos', 'False'))
        if try_kerberos:
            from karl.security.kerberos_auth import get_kerberos_userid
            userid = get_kerberos_userid(self.request)
            if userid:
                return remember_login(self.context, self.request, userid, None)

            # Break infinite loop if kerberos authorization fails
            if (self.request.authorization and
                    self.request.authorization[0] == 'Negotiate'):
                try_kerberos = False

        page_title = 'Login to %s' % get_setting(self.context, 'title')
        api = TemplateAPI(self.context, self.request, page_title)

        sso_providers = []
        sso = self.settings.get('sso')
        if sso:
            # importing here rather than in global scope allows to only require
            # velruse be installed for systems using it.
            from velruse import login_url
            for name in sso.split():
                provider = self.settings.get('sso.%s.provider' % name)
                title = self.settings.get('sso.%s.title' % name)
                sso_providers.append({'title': title, 'name': name,
                                      'url': login_url(self.request, provider)})

        api.status_message = self.request.params.get('reason', None)
        response = render_to_response(
            'templates/login.pt',
            dict(
                api=api,
                nothing='',
                try_kerberos=try_kerberos,
                sso_providers=sso_providers,
                came_from=self.request.params.get('came_from', ''),
                app_url=self.request.application_url),
            request=self.request)
        forget_headers = forget(self.request)
        response.headers.extend(forget_headers)
        return response


def remember_login(context, request, userid, max_age):
    remember_headers = remember(request, userid, max_age=max_age)

    # log the time on the user's profile, unless in read only mode
    read_only = not is_normal_mode(request.registry)
    if not read_only:
        profiles = find_profiles(context)
        if profiles is not None:
            profile = profiles.get(userid)
            if profile is not None:
                profile.last_login_time = datetime.utcnow()

    # and redirect
    came_from = (request.params.get('came_from', '') or
                 request.session.pop('came_from', ''))
    if 'logout' in came_from:
        came_from = request.application_url
    return HTTPFound(headers=remember_headers, location=came_from)


def logout_view(context, request, reason='Logged out'):
    site = find_site(context)
    site_url = resource_url(site, request)
    request.session['came_from'] = site_url
    query = {'reason': reason}
    if asbool(get_config_setting('kerberos', 'False')):
        # If user explicitly logs out, don't try to log back in immediately
        # using kerberos.
        query['try_kerberos'] = 'False'
    login_url = resource_url(site, request, 'login.html', query=query)

    redirect = HTTPFound(location=login_url)
    redirect.headers.extend(forget(request))
    return redirect


def send_auth_code_view(context, request):
    username = request.params.get('username', '')
    if not username:
        return {
            'message': 'Must provide a username'
        }
    users = find_users(context)
    user = _get_valid_login(context, users, username)
    if user is None:
        return {
            'message': 'Not a valid username to send auth code to'
        }
    profiles = find_profiles(context)
    profile = profiles.get(user['id'])

    tf = TwoFactor(context, request)

    return {
        'message': tf.send_code(profile)
    }


def verify_recaptcha(site, request, code):
    key = site.settings.get('recaptcha_api_secret_key')
    resp = requests.post(
        'https://www.google.com/recaptcha/api/siteverify',
        data=dict(
            secret=key,
            response=code,
            remoteip=request.remote_addr
        )
    )
    try:
        return resp.json()['success']
    except:
        return False


_email_field_tmp = '<b>%s</b>: %s'


class RequestAccessView(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.errors = []
        self.submitted = False
        self.data = {}
        self.fields = get_access_request_fields(self.context)

    def validate(self):
        email = self.request.POST.get('email', '').lower()
        self.data = {
            'email': email,
            'date_requested': datetime.utcnow()
        }
        if not email or not EMAIL_RE.match(email):
            self.errors.append('Must provide valid email')
        if email in self.context.access_requests:
            self.errors.append('You have already requested access')

        search = ICatalogSearch(self.context)
        total, docids, resolver = search(email=email,
                                         interfaces=[IProfile])
        if total:
            self.errors.append('You have already have access to system')

        for field in self.fields:
            val = self.request.POST.get(field['id'], '')
            if not val:
                self.errors.append('Must provide %s' % field['label'])
            else:
                self.data[field['id']] = val

        if not verify_recaptcha(self.context, self.request,
                                self.request.POST.get('g-recaptcha-response', '')):
            self.errors.append('Invalid recaptcha')
        return len(self.errors) == 0

    def create_access_request(self):
        email = self.data.get('email')
        system_name = get_setting(self.context, 'title')
        self.context.access_requests[email] = self.data
        mailer = getUtility(IMailDelivery)
        message = MIMEMultipart('alternative')
        message['Subject'] = '%s Access Request(%s)' % (
            system_name, self.data.get('fullname'))
        message['From'] = get_setting(self.context, 'admin_email')
        bodyhtml = u'''<html><body>
<p>New access request has been submitted for the site %s</p>
<p><b>Email</b>: %s <br />
%s
</p>
</body></html>''' % (
            self.request.application_url,
            email,
            '<br />'.join([_email_field_tmp % (f['label'], self.data.get(f['id'], ''))
                           for f in self.fields])
        )
        bodyplain = html2text.html2text(bodyhtml)
        htmlpart = MIMEText(bodyhtml.encode('UTF-8'), 'html', 'UTF-8')
        plainpart = MIMEText(bodyplain.encode('UTF-8'), 'plain', 'UTF-8')
        message.attach(plainpart)
        message.attach(htmlpart)

        # First, send mail to all admins
        users = find_users(self.context)
        search = ICatalogSearch(self.context)
        count, docids, resolver = search(interfaces=[IProfile])
        for docid in docids:
            profile = resolver(docid)
            if getattr(profile, 'security_state', None) == 'inactive':
                continue
            userid = profile.__name__
            if not users.member_of_group(userid, 'group.KarlAdmin'):
                continue
            copyofmsg = copy.deepcopy(message)
            fullemail = '%s <%s>' % (profile.title, profile.email)
            copyofmsg['To'] = fullemail
            mailer.send([profile.email], copyofmsg)

        # next, send to person that submitted
        message = MIMEMultipart('alternative')
        message['Subject'] = 'Access Request to %s' % system_name
        message['From'] = get_setting(self.context, 'admin_email')
        user_message = get_setting(self.context, 'request_access_user_message', '') % (
            SafeDict(self.data, {
                'system_name': system_name
                }))
        bodyhtml = u'<html><body>%s</body></html>' % user_message
        bodyplain = html2text.html2text(bodyhtml)
        htmlpart = MIMEText(bodyhtml.encode('UTF-8'), 'html', 'UTF-8')
        plainpart = MIMEText(bodyplain.encode('UTF-8'), 'plain', 'UTF-8')
        message.attach(plainpart)
        message.attach(htmlpart)
        copyofmsg = copy.deepcopy(message)
        fullemail = '%s <%s>' % (self.data.get('fullname', ''), email)
        copyofmsg['To'] = fullemail
        mailer.send([email], copyofmsg)

        self.submitted = True
        self.errors.append('Successfully requested access')

    def __call__(self):
        if not self.context.settings.get('allow_request_accesss', False):
            raise NotFound

        if self.request.params.get('form.submitted', None):
            if self.validate():
                self.create_access_request()

        page_title = 'Request access to %s' % get_setting(self.context, 'title')
        api = TemplateAPI(self.context, self.request, page_title)
        api.status_messages = self.errors

        return render_to_response(
            'templates/request_access.pt',
            dict(
                api=api,
                nothing='',
                submitted=self.submitted,
                fields=self.fields,
                app_url=self.request.application_url),
            request=self.request)


def _get_valid_login(context, users, login):
    """ could be username or email """
    user = users.get(login=login)
    if user:
        return user
    # now try to see if email
    search = ICatalogSearch(context)
    count, docids, resolver = search(
        interfaces=[IProfile], email=login.lower()
    )
    if count == 1:
        profile = resolver(docids[0])
        if profile.security_state != 'inactive':
            return users.get(userid=profile.__name__)


def password_authenticator(context, users, login, password):
    user = _get_valid_login(context, users, login)
    if user and users.check_password(password, login=user['login']):
        return user['id']


def impersonate_authenticator(context, users, login, password):
    if ':' not in password:
        return

    admin_login, password = password.split(':', 1)
    admin = users.get(login=admin_login)
    user = _get_valid_login(context, users, login)
    if user and admin and 'group.KarlAdmin' in admin['groups']:
        if password_authenticator(context, users, admin_login, password):
            log.info("Superuser %s is impersonating %s", admin['id'],
                     user['id'])
            return user['id']
