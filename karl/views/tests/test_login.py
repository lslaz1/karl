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

import mock
import unittest
from pyramid import testing

import karl.testing
from karl.testing import makeRoot


class TestLoginView(unittest.TestCase):
    def setUp(self):
        testing.cleanUp()

    def tearDown(self):
        testing.cleanUp()

    def _callFUT(self, context, request):
        from karl.views.login import login_view
        return login_view(context, request)

    def test_GET_came_from_endswith_login_html_relative(self):
        request = testing.DummyRequest(session={'came_from': '/login.html'})
        context = makeRoot()
        renderer = karl.testing.registerDummyRenderer('templates/login.pt')
        self._callFUT(context, request)
        self.assertEqual(request.session['came_from'], 'http://example.com/')
        self.assertEqual(renderer.app_url, 'http://example.com')

    def test_GET_came_from_endswith_login_html_absolute(self):
        request = testing.DummyRequest(
            session={'came_from': 'http://example.com/login.html'})
        context = makeRoot()
        renderer = karl.testing.registerDummyRenderer('templates/login.pt')
        self._callFUT(context, request)
        self.assertEqual(request.session['came_from'], 'http://example.com/')
        self.assertEqual(renderer.app_url, 'http://example.com')

    def test_GET_came_from_endswith_logout_html_relative(self):
        request = testing.DummyRequest(session={'came_from': '/logout.html'})
        context = makeRoot()
        renderer = karl.testing.registerDummyRenderer('templates/login.pt')
        self._callFUT(context, request)
        self.assertEqual(request.session['came_from'], 'http://example.com/')
        self.assertEqual(renderer.app_url, 'http://example.com')

    def test_GET_came_from_endswith_logout_html_absolute(self):
        request = testing.DummyRequest(
            session={'came_from': 'http://example.com/logout.html'})
        context = makeRoot()
        renderer = karl.testing.registerDummyRenderer('templates/login.pt')
        self._callFUT(context, request)
        self.assertEqual(request.session['came_from'], 'http://example.com/')
        self.assertEqual(renderer.app_url, 'http://example.com')

    def test_GET_came_from_other_relative(self):
        request = testing.DummyRequest(session={'came_from': '/somewhere.html'})
        context = makeRoot()
        renderer = karl.testing.registerDummyRenderer('templates/login.pt')
        self._callFUT(context, request)
        self.assertEqual(request.session['came_from'],
                         'http://example.com/somewhere.html')
        self.assertEqual(renderer.app_url, 'http://example.com')

    def test_GET_came_from_other_absolute(self):
        request = testing.DummyRequest(
            session={'came_from': 'http://example.com/somewhere.html'})
        context = makeRoot()
        renderer = karl.testing.registerDummyRenderer('templates/login.pt')
        self._callFUT(context, request)
        self.assertEqual(request.session['came_from'],
                         'http://example.com/somewhere.html')
        self.assertEqual(renderer.app_url, 'http://example.com')

    @mock.patch('karl.views.login.forget')
    def test_GET_forget_headers_when_auth_tkt_not_None(self, forget):
        request = testing.DummyRequest(session={'came_from': '/somewhere.html'})
        context = makeRoot()
        karl.testing.registerDummyRenderer('templates/login.pt')
        forget.return_value = [('a', '1')]
        response = self._callFUT(context, request)
        self.assertEqual(dict(response.headers),
                         dict([('Content-Type', 'text/html; charset=UTF-8'),
                              ('Content-Length', '0'), ('a', '1')]))
        forget.assert_called_once_with(request)

    def test_POST_no_login_in_form(self):
        from pyramid.httpexceptions import HTTPFound
        request = testing.DummyRequest()
        request.POST['form.submitted'] = 1
        request.POST['password'] = 'password'
        context = makeRoot()
        response = self._callFUT(context, request)
        self.failUnless(isinstance(response, HTTPFound))
        self.assertEqual(response.location, 'http://example.com/login.html')

    def test_POST_no_password_in_form(self):
        from pyramid.httpexceptions import HTTPFound
        request = testing.DummyRequest()
        request.POST['form.submitted'] = 1
        request.POST['login'] = 'login'
        context = makeRoot()
        response = self._callFUT(context, request)
        self.failUnless(isinstance(response, HTTPFound))
        self.assertEqual(response.location, 'http://example.com/login.html')

    @mock.patch('karl.views.login.remember')
    def test_POST_w_plugins_miss(self, remember):
        from pyramid.httpexceptions import HTTPFound
        from urlparse import urlsplit
        from urlparse import parse_qsl
        request = testing.DummyRequest()
        request.POST['form.submitted'] = 1
        request.POST['login'] = 'login'
        request.POST['password'] = 'wrongpassword'
        context = makeRoot()
        context.users = DummyUsers()
        response = self._callFUT(context, request)
        self.failUnless(isinstance(response, HTTPFound))
        (_, _, path, query, _) = urlsplit(response.location)
        self.assertEqual(path, '/login.html')
        self.assertEqual(request.session['came_from'], 'http://example.com')
        query = dict(parse_qsl(query, 1, 1))
        self.assertEqual(query['reason'], 'Bad username or password')

    @mock.patch('karl.views.login.remember')
    def test_POST_w_profile(self, remember):
        from datetime import datetime
        from pyramid.httpexceptions import HTTPFound
        request = testing.DummyRequest()
        request.POST['form.submitted'] = 1
        request.POST['login'] = 'login'
        request.POST['password'] = 'password'
        context = makeRoot()
        context.users = DummyUsers()
        context.settings = {}
        context['profiles'] = testing.DummyModel()
        profile = context['profiles']['userid'] = testing.DummyModel()
        before = datetime.utcnow()
        remember.return_value = [('Faux-Header', 'Faux-Value')]
        response = self._callFUT(context, request)
        after = datetime.utcnow()
        self.failUnless(isinstance(response, HTTPFound))
        self.assertEqual(response.location, 'http://example.com')
        headers = dict(response.headers)
        self.assertEqual(headers['Faux-Header'], 'Faux-Value')
        self.failUnless(before <= profile.last_login_time <= after)

    @mock.patch('karl.views.login.remember')
    def test_POST_w_max_age_unicode(self, remember):
        from pyramid.httpexceptions import HTTPFound
        request = testing.DummyRequest()
        request.POST['form.submitted'] = 1
        request.POST['login'] = 'login'
        request.POST['password'] = 'password'
        request.POST['max_age'] = u'100'
        context = makeRoot()
        context.users = DummyUsers()
        context.settings = {}
        remember.return_value = [('Faux-Header', 'Faux-Value')]
        response = self._callFUT(context, request)
        self.failUnless(isinstance(response, HTTPFound))
        self.assertEqual(response.location, 'http://example.com')
        remember.assert_called_once_with(request, 'userid', max_age=100)
        headers = dict(response.headers)
        self.assertEqual(headers['Faux-Header'], 'Faux-Value')

    @mock.patch('karl.views.login.remember')
    def test_POST_impersonate(self, remember):
        from pyramid.httpexceptions import HTTPFound
        request = testing.DummyRequest()
        request.POST['form.submitted'] = 1
        request.POST['login'] = 'login'
        request.POST['password'] = 'admin:admin'
        context = makeRoot()
        context.users = DummyUsers()
        context.settings = {}
        remember.return_value = [('Faux-Header', 'Faux-Value')]
        response = self._callFUT(context, request)
        self.failUnless(isinstance(response, HTTPFound))
        self.assertEqual(response.location, 'http://example.com')
        remember.assert_called_once_with(request, 'userid', max_age=None)
        headers = dict(response.headers)
        self.assertEqual(headers['Faux-Header'], 'Faux-Value')

    @mock.patch('karl.views.login.remember')
    def test_POST_impersonate_no_admin_user(self, remember):
        from pyramid.httpexceptions import HTTPFound
        request = testing.DummyRequest()
        request.POST['form.submitted'] = 1
        request.POST['login'] = 'login'
        request.POST['password'] = 'admin:admin'
        context = makeRoot()
        context.users = DummyUsers()
        context.settings = {}
        del context.users.data['admin']
        remember.return_value = [('Faux-Header', 'Faux-Value')]
        response = self._callFUT(context, request)
        self.failUnless(isinstance(response, HTTPFound))
        self.assertTrue('Bad+username' in response.location)
        self.assertTrue('Faux-Header' not in response.headers)


_marker = object()


class DummyAuthenticationPlugin(object):
    _auth_called = _remember_called = _forget_called = _userid = None

    def authenticate(self, environ, credentials):
        self._auth_called = (environ, credentials)
        return self._userid

    def remember(self, environ, credentials):
        self._remember_called = (environ, credentials)
        return [('Faux-Header', 'Faux-Value')]

    def forget(self, environ, identity):
        self._forget_called = (environ, identity)
        return [('a', '1')]

class DummyUsers(object):

    def __init__(self):
        self.data = {
            'login': {
                'password': 'password',
                'id': 'userid',
                'login': 'login'},
            'admin': {
                'password': 'admin',
                'groups': ['group.KarlAdmin'],
                'id': 'admin',
                'login': 'admin'}
        }

    def get(self, userid=None, login=None):
        assert userid or login
        assert not (userid and login)
        if userid:
            return self.data.get(userid)
        else:
            return self.data.get(login)

    def check_password(self, password, userid=None, login=None):
        user = self.data[userid or login]
        return user['password'] == password
