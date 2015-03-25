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

from karl.models.interfaces import IObjectModifiedEvent
from karl.models.interfaces import IObjectWillBeModifiedEvent
from karl.models.interfaces import ILoginAttempt
from karl.models.interfaces import ILoginSuccess
from karl.models.interfaces import ILoginFailed

from zope.interface import implements


class ObjectModifiedEvent(object):
    implements(IObjectModifiedEvent)
    def __init__(self, object):
        self.object = object


class ObjectWillBeModifiedEvent(object):
    implements(IObjectWillBeModifiedEvent)
    def __init__(self, object):
        self.object = object


class LoginAttempt(object):
    implements(ILoginAttempt)

    def __init__(self, site, request, login, password):
        self.site = site
        self.request = request
        self.login = login
        self.password = password


class LoginFailed(LoginAttempt):
    implements(ILoginFailed)


class LoginSuccess(LoginAttempt):
    implements(ILoginSuccess)