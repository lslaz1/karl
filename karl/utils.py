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

import calendar
import copy

from zope.component import queryAdapter
from zope.component import queryMultiAdapter
from zope.component import queryUtility

from pyramid.interfaces import ISettings
from pyramid.traversal import find_root
from pyramid.traversal import find_interface
from repoze.lemonade.content import get_content_type

from karl.models.interfaces import ICatalogSearch
from karl.models.interfaces import ICommunity
from karl.models.interfaces import ISite
from karl.models.interfaces import IAttachmentPolicy
from karl.models.interfaces import IPeopleDirectory
from karl.models.tempfolder import TempFolder
from karl.views.interfaces import IFolderAddables
from karl.views.interfaces import ILayoutProvider

from lxml.html import fromstring, tostring

import time
from datetime import datetime
import hashlib
import random
try:
    random = random.SystemRandom()
    using_sysrandom = True
except NotImplementedError:
    using_sysrandom = False

from hashlib import sha256 as sha
from urllib2 import unquote

_marker = object()


def find_site(context):
    site = find_interface(context, ISite)
    if site is None:
        # for unittesting convenience
        site = find_root(context)
    return site


def find_users(context):
    return getattr(find_site(context), 'users', None)


def find_catalog(context):
    return getattr(find_site(context), 'catalog', None)


def find_events(context):
    return getattr(find_site(context), 'events', None)


def find_tags(context):
    return getattr(find_site(context), 'tags', None)


def find_profiles(context):
    return find_site(context).get('profiles')


def find_community(context):
    return find_interface(context, ICommunity)


def find_communities(context):
    return find_site(context).get('communities')


def find_peopledirectory(context):
    site = find_site(context)
    people = site.get('people', None)
    if people is not None and not IPeopleDirectory.providedBy(people):
        # wrong kind of people directory
        return None
    return people


def find_peopledirectory_catalog(context):
    site = find_site(context)
    people = site.get('people', None)
    if not people:
        return None
    return getattr(people, 'catalog', None)


def get_setting(context, setting_name, default=_marker):
    site = find_site(context)
    if default is _marker:
        try:
            # use default settings defined on Site object
            from karl.models.site import Site
            default = Site._default_settings.get(setting_name, None)
        except AttributeError:
            default = None
    try:
        return site.settings.get(setting_name, default)
    except AttributeError:
        return default


def get_settings(context):
    site = find_site(context)
    try:
        return site.settings
    except AttributeError:
        from karl.models.site import Site
        return Site._default_settings


def get_config_setting(setting_name, default=None):
    # Grab a setting from ISettings.  (context is ignored.)
    settings = queryUtility(ISettings)
    if settings is not None:
        return settings.get(setting_name, default)
    return default


def get_config_settings():
    return queryUtility(ISettings)


def get_content_type_name(resource):
    content_iface = get_content_type(resource)
    return content_iface.getTaggedValue('name')


def get_content_type_name_and_icon(resource):
    content_iface = get_content_type(resource)
    return (content_iface.getTaggedValue('name'),
            content_iface.queryTaggedValue('icon', 'blue-document.png'))


def debugsearch(context, **kw):
    searcher = ICatalogSearch(context)
    kw['use_cache'] = False
    num, docids, resolver = searcher(**kw)
    L = []
    for docid in docids:
        L.append(resolver(docid))
    return num, L


def get_session(context, request):
    site = find_site(context)
    session = site.sessions.get(request.environ['repoze.browserid'])
    return session


_MAX_32BIT_INT = int((1 << 31) - 1)


def docid_to_hex(docid):
    return '%08X' % (_MAX_32BIT_INT + docid)


def hex_to_docid(hex):
    return int('%s' % hex, 16) - _MAX_32BIT_INT


def asbool(s):
    s = str(s).strip()
    return s.lower() in ('t', 'true', 'y', 'yes', 'on', '1')


def coarse_datetime_repr(date):
    """Convert a datetime to an integer with 100 second granularity.

    The granularity reduces the number of index entries in the
    catalog.
    """
    timetime = calendar.timegm(date.timetuple())
    return int(timetime) // 100


def support_attachments(context):
    """Return true if the given object should support attachments"""
    adapter = queryAdapter(context, IAttachmentPolicy)
    if adapter:
        return adapter.support()
    else:
        # support attachments by default
        return True


class PersistentBBB(object):
    """ A descriptor which fixes up old persistent instances with a
    default value as a 'write on read' operation.  This is usually not
    useful if the default value isn't mutable, and arguably 'write on
    read' behavior is evil.  Note that this descriptor returns the
    value after *replacing itself* on the instance with the value."""
    def __init__(self, name, val):
        self.name = name
        self.val = val

    def __get__(self, inst, cls):
        setattr(inst, self.name, copy.deepcopy(self.val))
        return getattr(inst, self.name)


def get_layout_provider(context, request):
    from karl.content.views.adapters import DefaultLayoutProvider
    return queryMultiAdapter((context, request), ILayoutProvider,
                             default=DefaultLayoutProvider(context, request))


def get_folder_addables(context, request):
    from karl.content.views.adapters import DefaultFolderAddables
    return queryMultiAdapter((context, request), IFolderAddables,
                             default=DefaultFolderAddables(context, request))


def find_tempfolder(context):
    root = find_root(context)
    if 'TEMP' not in root:
        root['TEMP'] = TempFolder()
    return root['TEMP']


def find_repo(context):
    return getattr(find_site(context), 'repo', None)


# generated when process started, hard to guess
SECRET = random.randint(0, 1000000)


def get_random_string(length=12,
                      allowed_chars='abcdefghijklmnopqrstuvwxyz'
                                    'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'):
    """
    Returns a securely generated random string.

    The default length of 12 with the a-z, A-Z, 0-9 character set returns
    a 71-bit value. log_2((26+26+10)^12) =~ 71 bits
    """
    if not using_sysrandom:
        # This is ugly, and a hack, but it makes things better than
        # the alternative of predictability. This re-seeds the PRNG
        # using a value that is hard for an attacker to predict, every
        # time a random string is required. This may change the
        # properties of the chosen random sequence slightly, but this
        # is better than absolute predictability.
        random.seed(
            sha(
                "%s%s%s" % (
                    random.getstate(),
                    time.time(),
                    SECRET)
                ).digest())
    return ''.join([random.choice(allowed_chars) for i in range(length)])


def make_random_code(length=255):
    prehash = hashlib.sha1(str(get_random_string(length)).encode('utf-8')).hexdigest()[:5]
    return hashlib.sha1(
        (prehash + str(datetime.now().microsecond)).encode('utf-8')).hexdigest()[:length]


def strings_differ(string1, string2):
    """Check whether two strings differ while avoiding timing attacks.

    This function returns True if the given strings differ and False
    if they are equal.  It's careful not to leak information about *where*
    they differ as a result of its running time, which can be very important
    to avoid certain timing-related crypto attacks:

        http://seb.dbzteam.org/crypto/python-oauth-timing-hmac.pdf

    """
    if len(string1) != len(string2):
        return True

    invalid_bits = 0
    for a, b in zip(string1, string2):
        invalid_bits += a != b

    return invalid_bits != 0


def strings_same(string1, string2):
    return not strings_differ(string1, string2)


_egg_version_cache = {}


def get_egg_rev(distribution='karl'):
    if distribution in _egg_version_cache:
        return _egg_version_cache[distribution]
    import pkg_resources
    version = pkg_resources.get_distribution(distribution).version
    _egg_version_cache[distribution] = version
    return version


class SafeDict(object):
    def __init__(self, *dicts):
        self.overrides = {}
        self.dicts = [self.overrides] + list(dicts)

    def __getitem__(self, name, default=u''):
        for dd in self.dicts:
            val = dd.get(name, _marker)
            if val != _marker:
                if not isinstance(val, basestring):
                    try:
                        val = str(val)
                    except:
                        val = repr(val)
                return val
        return default

    def get(self, name, default=u''):
        for dd in self.dicts:
            val = dd.get(name, _marker)
            if val != _marker:
                return val

    def __setitem__(self, name, value):
        self.overrides[name] = value

    def copy(self):
        return SafeDict(*self.dicts)


def mailify_html(request, html):
    xml = fromstring(html)
    app = request.registry['application']
    for img in xml.cssselect('img'):
        src = img.attrib.get('src', '')
        if src.startswith(request.application_url):
            path = unquote(src[len(request.application_url):])
            resp = app.invoke_subrequest(request, path)

            if resp.status_int != 200:
                img.attrib['src'] = ''
                continue
            try:
                split = resp.headers.get('content-type', '').split('charset=')
                encoding = None
                ctype = split[0]
                if len(split) > 1:
                    encoding = split[1]
                ctype = ctype.split(';')[0]
                # pisa only likes ascii css
                data = resp.body
                if encoding:
                    data = data.decode(encoding).encode('ascii', errors='ignore')
            except ValueError:
                ctype = resp.headers.get('content-type', '').split(';')[0]
                data = resp.body

            data = data.encode("base64").replace("\n", "")
            data_uri = 'data:{0};base64,{1}'.format(ctype, data)
            img.attrib['src'] = data_uri
    return tostring(xml)
