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

from datetime import datetime
from datetime import timedelta
from urlparse import urljoin
import re
import requests

from karl.models.users import get_sha_password

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
from karl.utils import make_random_code
from karl.utils import strings_differ
from karl.models.interfaces import ICatalogSearch
from karl.models.interfaces import IProfile
from karl import events

from karl.views.api import TemplateAPI

from zope.component import getUtility
from zope.event import notify
from repoze.sendmail.interfaces import IMailDelivery
from repoze.postoffice.message import Message

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'[^@]+@[^@]+\.[^@]+')


def _fixup_came_from(request, came_from):
    came_from = urljoin(request.application_url, came_from)
    if came_from.endswith('login.html'):
        came_from = came_from[:-len('login.html')]
    elif came_from.endswith('logout.html'):
        came_from = came_from[:-len('logout.html')]
    return came_from


def login_view(context, request):
    settings = request.registry.settings
    came_from = request.session.get('came_from', request.url)
    came_from = _fixup_came_from(request, came_from)
    request.session['came_from'] = came_from

    if request.params.get('form.submitted', None) is not None:
        # identify
        login = request.POST.get('login')
        password = request.POST.get('password')

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
            userid = authenticate(users, login, password)
            if userid:
                break

        # if not successful, try again
        if not userid:
            notify(events.LoginFailed(context, request, login, password))
            redirect = request.resource_url(
                request.root, 'login.html', query={'reason': reason})
            return HTTPFound(location=redirect)

        if context.settings.get('two_factor_enabled', False):
            code = request.POST.get('code')
            if not code:
                redirect = request.resource_url(
                    request.root, 'login.html',
                    query={'reason': 'No authentication code provided'})
                notify(events.LoginFailed(context, request, login, password))
                return HTTPFound(location=redirect)
            profiles = find_profiles(context)
            profile = profiles.get(userid)
            window = context.settings.get('two_factor_auth_code_valid_duration', 300)
            now = datetime.utcnow()
            if (strings_differ(code, profile.current_auth_code) or
                    now > (profile.current_auth_code_time_stamp + timedelta(seconds=window))):  # noqa
                notify(events.LoginFailed(context, request, login, password))
                redirect = request.resource_url(
                    request.root, 'login.html', query={'reason': 'Invalid authorization code'})  # noqa
                return HTTPFound(location=redirect)

        # else, remember
        notify(events.LoginSuccess(context, request, login, password))
        return remember_login(context, request, userid, max_age)

    # Log in user seamlessly with kerberos if enabled
    try_kerberos = request.GET.get('try_kerberos', None)
    if try_kerberos:
        try_kerberos = asbool(try_kerberos)
    else:
        try_kerberos = asbool(get_config_setting('kerberos', 'False'))
    if try_kerberos:
        from karl.security.kerberos_auth import get_kerberos_userid
        userid = get_kerberos_userid(request)
        if userid:
            return remember_login(context, request, userid, None)

        # Break infinite loop if kerberos authorization fails
        if request.authorization and request.authorization[0] == 'Negotiate':
            try_kerberos = False

    page_title = 'Login to %s' % get_setting(context, 'title')
    api = TemplateAPI(context, request, page_title)

    sso_providers = []
    sso = settings.get('sso')
    if sso:
        # importing here rather than in global scope allows to only require
        # velruse be installed for systems using it.
        from velruse import login_url
        for name in sso.split():
            provider = settings.get('sso.%s.provider' % name)
            title = settings.get('sso.%s.title' % name)
            sso_providers.append({'title': title, 'name': name,
                                  'url': login_url(request, provider)})

    api.status_message = request.params.get('reason', None)
    response = render_to_response(
        'templates/login.pt',
        dict(
            api=api,
            nothing='',
            try_kerberos=try_kerberos,
            sso_providers=sso_providers,
            app_url=request.application_url),
        request=request)
    forget_headers = forget(request)
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
    came_from = request.session.pop('came_from')
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
    user = users.get_by_login(username)
    if user is None:
        return {
            'message': 'Not a valid username to send auth code to'
        }
    profiles = find_profiles(context)
    profile = profiles.get(user['id'])

    # get and set current auth code
    profile.current_auth_code = make_random_code(8)
    profile.current_auth_code_time_stamp = datetime.utcnow()

    mailer = getUtility(IMailDelivery)
    message = Message()
    message['From'] = get_setting(context, 'admin_email')
    message['To'] = '%s <%s>' % (profile.title, profile.email)
    message['Subject'] = '%s Authorization Request' % context.title
    body = u'''<html><body>
<p>An authorization code has been requested for the site %s.</p>
<p>Authorization Code: <b>%s</b></p>
</body></html>''' % (
        request.application_url,
        profile.current_auth_code
    )
    message.set_payload(body.encode('UTF-8'), 'UTF-8')
    message.set_type('text/html')
    mailer.send([profile.email], message)

    return {
        'message': 'Authorization code has been sent'
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


def request_access_view(context, request):
    if not context.settings.get('allow_request_accesss', False):
        raise NotFound

    error = None
    submitted = False
    if request.params.get('form.submitted', None) is not None:
        email = request.POST.get('email', '')
        name = request.POST.get('fullname', '')
        if not email or not EMAIL_RE.match(email):
            error = 'Must provide valid email'
        if not name:
            error = 'Must provide full name'
        if email in context.access_requests:
            error = 'You have already requested access'

        if not verify_recaptcha(context, request,
                                request.POST.get('g-recaptcha-response', '')):
            error = 'Invalid recaptcha'

        if not error:
            # add access request
            context.access_requests[email] = {
                'email': email,
                'fullname': name,
                'date_requested': datetime.utcnow()
            }
            mailer = getUtility(IMailDelivery)
            message = Message()
            message['Subject'] = '%s Access Request(%s)' % (
                context.title, name)
            message['From'] = get_setting(context, 'admin_email')
            body = u'''<html><body>
<p>New access request has been submitted for the site %s</p>
<p><b>Email</b>: %s <br />
   <b>Name</b>: %s <br />
</p>
</body></html>''' % (
                request.application_url,
                email,
                name
            )
            message.set_payload(body.encode('UTF-8'), 'UTF-8')
            message.set_type('text/html')
            # send mail to all admins
            users = find_users(context)
            search = ICatalogSearch(context)
            count, docids, resolver = search(interfaces=[IProfile])
            for docid in docids:
                profile = resolver(docid)
                if getattr(profile, 'security_state', None) == 'inactive':
                    continue
                userid = profile.__name__
                if not users.member_of_group(userid, 'group.KarlAdmin'):
                    continue
                message['To'] = '%s <%s>' % (profile.title, profile.email)
                mailer.send([profile.email], message)
            submitted = True
            error = 'Successfully requested access'

    page_title = 'Request access to %s' % context.title
    api = TemplateAPI(context, request, page_title)
    api.status_message = error
    return render_to_response(
        'templates/request_access.pt',
        dict(
            api=api,
            nothing='',
            submitted=submitted,
            app_url=request.application_url),
        request=request)


def password_authenticator(users, login, password):
    user = users.get(login=login)
    if user and not strings_differ(user['password'], get_sha_password(password)):
        return user['id']


def impersonate_authenticator(users, login, password):
    if ':' not in password:
        return

    admin_login, password = password.split(':', 1)
    admin = users.get(login=admin_login)
    user = users.get(login=login)
    if user and admin and 'group.KarlAdmin' in admin['groups']:
        if password_authenticator(users, admin_login, password):
            log.info("Superuser %s is impersonating %s", admin['id'],
                     user['id'])
            return user['id']