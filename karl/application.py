import datetime
import os
import sys
import time
import re

from zope.component import queryUtility

from repoze.depinj import lookup

import transaction

from pyramid.config import Configurator as BaseConfigurator
from pyramid.authentication import AuthTktAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.events import NewRequest
from pyramid.httpexceptions import HTTPMethodNotAllowed
from pyramid.session import UnencryptedCookieSessionFactoryConfig as Session
from pyramid.util import DottedNameResolver

from pyramid_zodbconn import get_connection

from karl.bootstrap.interfaces import IBootstrapper
from karl.models.site import get_weighted_textrepr
from karl.textindex import KarlPGTextIndex
from karl.utils import find_users
from karl.utils import asbool
from karl import renderers
import karl.includes
import perfmetrics

try:
    import pyramid_debugtoolbar
    pyramid_debugtoolbar  # pyflakes stfu
except ImportError:
    pyramid_debugtoolbar = None

try:
    import slowlog
    slowlog  # ode to pyflakes
except ImportError:
    slowlog = None


class CSSFile(object):

    def __init__(self, path, always_include=False, ie_expression=None):
        self.path = path
        self.ie_expression = ie_expression
        self.always_include = always_include

    def render(self, request):
        full_path = '%s/%s' % (
            request.application_url.rstrip('/'),
            self.path.lstrip('/'))
        if self.ie_expression:
            return '''<!--[if %s]> <style type="text/css" media="all">@import
  url(%s);</style>
<![endif]-->''' % (self.ie_expression, full_path)
        else:
            return '''<link rel="stylesheet"
href="%s" type="text/css"/>''' % full_path


class CSSResources(object):

    def __init__(self):
        self.data = {}
        self.order = []

    def add(self, name, path, **kwargs):
        self.data[name] = CSSFile(path, **kwargs)
        if name not in self.order:
            self.order.append(name)

    def get(self, name):
        return self.data.get(name)

    def get_all(self, request):
        files = []
        included_here = request.environ.get('required_css', [])
        for name in self.order:
            resource = self.data[name]
            if resource.always_include or name in included_here:
                files.append(resource)
        return files

    def require(self, request, name):
        if 'required_css' not in request.environ:
            request.environ['required_css'] = set([])
        request.environ['required_css'].add(name)

    def disable(self, request, name):
        if 'required_css' not in request.environ:
            request.environ['required_css'] = set([])
        if name in request.environ['required_css']:
            request.environ['required_css'].remove(name)


class Configurator(BaseConfigurator):

    def __init__(self, *args, **kwargs):
        super(Configurator, self).__init__(*args, **kwargs)
        self.registry['css_resources'] = CSSResources()

    def define_css(self, name, path, **kwargs):
        self.registry['css_resources'].add(name, path, **kwargs)


def configure_karl(config, load_zcml=True):
    # Authorization/Authentication policies
    settings = config.registry.settings
    authentication_policy = AuthTktAuthenticationPolicy(
        settings['who_secret'],
        callback=group_finder,
        cookie_name=settings['who_cookie']
    )
    config.set_authorization_policy(ACLAuthorizationPolicy())
    config.set_authentication_policy(authentication_policy)
    # Static tree revisions routing
    static_rev = settings.get('static_rev')
    if not static_rev:
        static_rev = _guess_static_rev()
        settings['static_rev'] = static_rev
    static_path = '/static/%s' % static_rev
    config.add_static_view(
        static_path, 'karl.views:static',
        cache_max_age=60 * 60 * 24 * 365)
    # Add a redirecting static view to all _other_ revisions.
    def _expired_static_predicate(info, request):
        # We add a redirecting route to all static/*,
        # _except_ if it starts with the active revision segment.
        path = info['match']['path']
        return path and path[0] != static_rev
    config.add_route(
        'expired-static', '/static/*path',
        custom_predicates=(_expired_static_predicate, ))

    # Need a session if using Velruse
    config.set_session_factory(Session(settings['who_secret']))

    config.include('karl.security.sso')

    if load_zcml:
        config.hook_zca()
        config.include('pyramid_zcml')
        config.load_zcml('standalone.zcml')

    debug = asbool(settings.get('debug', 'false'))
    if not debug:
        config.add_view('karl.errorpage.errorpage', context=Exception,
                        renderer="karl.views:templates/errorpage.pt")

    debugtoolbar = asbool(settings.get('debugtoolbar', 'false'))
    if debugtoolbar and pyramid_debugtoolbar:
        config.include(pyramid_debugtoolbar)

    config.add_subscriber(block_webdav, NewRequest)

    if slowlog is not None:
        config.include(slowlog)

    if perfmetrics is not None:
        config.include(perfmetrics)

    if isinstance(config, Configurator):
        # define css only if config is correct instance type
        # this caused some tests to fail...
        config.define_css('karl-wikitoc', static_path + '/karl-wikitoc.css')
        config.define_css('karl-multifileupload',
                          static_path + '/karl-multifileupload.css')
        config.define_css('karl-ui', static_path + '/karl-ui.css',
                          always_include=True)
        config.define_css('karl-base', static_path + '/karl-base.css',
                          always_include=True)
        config.define_css('karl-theme', static_path + '/karl-theme.css',
                          always_include=True)
        config.define_css(
            'karl-ie', static_path + '/karl_ie.css',
            always_include=True, ie_expression='lte IE 8')
        config.define_css(
            'karl-ie8', static_path + '/karl_ie8.css',
            always_include=True, ie_expression='IE 8')
        config.define_css(
            'karl-ie9', static_path + '/karl_ie9.css',
            always_include=True, ie_expression='gte IE 9')


def block_webdav(event):
    """
    Microsoft Office will now cause Internet Explorer to attempt to open Word
    Docs using WebDAV when viewing Word Docs in the browser.  It is imperative
    that we disavow any knowledge of WebDAV to prevent IE from doing insane
    things.

    http://serverfault.com/questions/301955/
    """
    if event.request.method in ('PROPFIND', 'OPTIONS'):
        raise HTTPMethodNotAllowed(event.request.method)


def group_finder(identity, request):
    # XXX Might be old repoze.who policy which uses an identity dict
    if isinstance(identity, dict):
        return identity['groups']

    # Might be cached
    user = request.environ.get('karl.identity')
    if user is None:
        users = find_users(request.context)
        user = users.get(identity)
    if user is None:
        return None
    request.environ['karl.identity'] = user  # cache for later
    return user['groups']


def _guess_static_rev():
    """Guess an appropriate static revision number.

    This is only used when no deployment tool set the static_rev
    for us.  Deployment tools should set static_rev because
    karl can only guess what static revisions are appropriate,
    while deployment tools can set a system-wide revision number
    that encompasses all relevant system changes.
    """
    # If Karl is installed as an egg, we can try to get the Karl version
    # number from the egg and use that.
    _static_rev = _get_egg_rev()

    if _static_rev is not None:
        return _static_rev

    # Fallback to just using a timestamp.  This is guaranteed not to fail
    # but will create different revisions for each process, resulting in
    # some extra static resource downloads
    _static_rev = 'r%d' % int(time.time())

    return _static_rev


def _get_egg_rev():
    import pkg_resources
    return pkg_resources.get_distribution("karl").version


def root_factory(request, name='site'):
    connstats_file = request.registry.settings.get(
        'connection_stats_filename')
    connstats_threshhold = float(request.registry.settings.get(
        'connection_stats_threshhold', 0))
    def finished(request):
        # closing the primary also closes any secondaries opened
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed = time.time() - before
        if elapsed > connstats_threshhold:
            loads_after, stores_after = connection.getTransferCounts()
            loads = loads_after - loads_before
            stores = stores_after - stores_before
            with open(connstats_file, 'a', 0) as f:
                f.write('"%s", "%s", "%s", %f, %d, %d\n' % (
                    now, request.method, request.path_url, elapsed,
                    loads, stores)
                )
                f.flush()

    # NB: Finished callbacks are executed in the order they've been added
    # to the request.  pyramid_zodbconn's ``get_connection`` registers a
    # finished callback which closes the ZODB database.  Because the
    # finished callback it registers closes the database, we need it to
    # execute after the "finished" function above.  As a result, the above
    # call to ``request.add_finished_callback`` *must* be executed before
    # we call ``get_connection`` below.

    # Rationale: we want the call to getTransferCounts() above to happen
    # before the ZODB database is closed, because closing the ZODB database
    # has the side effect of clearing the transfer counts (the ZODB
    # activity monitor clears the transfer counts when the database is
    # closed).  Having the finished callbacks called in the "wrong" order
    # will result in the transfer counts being cleared before the above
    # "finished" function has a chance to read their per-request values,
    # and they will appear to always be zero.

    if connstats_file is not None:
        request.add_finished_callback(finished)

    connection = get_connection(request)

    if connstats_file is not None:
        before = time.time()
        loads_before, stores_before = connection.getTransferCounts()

    folder = connection.root()
    if name not in folder:
        from karl.bootstrap.bootstrap import populate  # avoid circdep
        bootstrapper = queryUtility(IBootstrapper, default=populate)
        bootstrapper(folder, name, request)

        # Use pgtextindex
        if 'pgtextindex.dsn' in request.registry.settings:
            site = folder.get(name)
            index = lookup(KarlPGTextIndex)(
                get_weighted_textrepr, drop_and_create=True)
            site.catalog['texts'] = index

        transaction.commit()

    return folder[name]


def main(global_config, **settings):
    return Application(global_config, **settings)


class Application(object):

    def __init__(self, global_config, **settings):
        var = os.path.abspath(settings['var'])
        if 'mail_queue_path' not in settings:
            settings['mail_queue_path'] = os.path.join(var, 'mail_queue')
        if 'error_monitor_dir' not in settings:
            settings['error_monitor_dir'] = os.path.join(var, 'errors')
        if 'blob_cache' not in settings:
            settings['blob_cache'] = os.path.join(var, 'blob_cache')
        if 'var_instance' not in settings:
            settings['var_instance'] = os.path.join(var, 'instance')
        if 'var_tmp' not in settings:
            settings['var_tmp'] = os.path.join(var, 'tmp')

        # Configure timezone
        tz = settings.get('timezone')
        if tz is not None:
            os.environ['TZ'] = tz
            time.tzset()

        # Find package and configuration
        packages = []
        configurers = []
        for pkg_name in settings.get('packages', '').splitlines():
            try:
                __import__(pkg_name)
                package = sys.modules[pkg_name]
                packages.append(package)
                configure_overrides = get_imperative_config(package)
                if configure_overrides:
                    configurers.append(configure_overrides)
            except ImportError:
                pass

        config = Configurator(
            package=karl.includes,
            settings=settings,
            root_factory=root_factory,
            autocommit=True
            )

        config.begin()
        config.include('pyramid_tm')
        config.include('pyramid_zodbconn')

        configure_karl(config)
        config.commit()

        for configurer in configurers:
            configurer(config)
            config.commit()

        renderer = renderers.AddonRendererFactoryFactory(packages)
        config.add_renderer('.pt', renderer)

        config.end()

        def closer():
            registry = config.registry
            dbs = getattr(registry, '_zodb_databases', None)
            if dbs:
                for db in dbs.values():
                    db.close()
                del registry._zodb_databases

        app = config.make_wsgi_app()
        app.config = settings
        app.close = closer

        self.app = app
        self.config = config
        self.path_prefix = settings.get('path_prefix', '/').rstrip('/')
        self.regprefix = re.compile("^%s(.*)$" % self.path_prefix)
        self.settings = settings
        self.config.registry['application'] = self
        self.renderer = renderer

        # copy some wsgi app attriutes over...
        for attr in ('threadlocal_manager', 'logger', 'root_factory', 'routes_mapper',
                     'request_factory', 'handle_request', 'root_policy', 'registry'):
            setattr(self, attr, getattr(app, attr, None))

    def _rewrite(self, environ):
        """
        handle proxy headers and rewrite wsgi environment to work correctly
        with those headers
        and handle a potential path_prefix value
        """
        url = environ['PATH_INFO']
        url = re.sub(self.regprefix, r'\1', url)
        if not url:
            url = '/'
        environ['PATH_INFO'] = url
        environ['SCRIPT_NAME'] = self.path_prefix

        if 'HTTP_X_FORWARDED_SERVER' in environ:
            environ['SERVER_NAME'] = environ['HTTP_HOST'] = environ.pop(
                'HTTP_X_FORWARDED_SERVER').split(',')[0]
        if 'HTTP_X_FORWARDED_HOST' in environ:
            environ['HTTP_HOST'] = environ.pop('HTTP_X_FORWARDED_HOST').split(',')[0]
        if 'HTTP_X_FORWARDED_FOR' in environ:
            environ['REMOTE_ADDR'] = environ.pop('HTTP_X_FORWARDED_FOR')

        if self.settings.get('url_scheme') is not None:
            environ['wsgi.url_scheme'] = self.settings.get('url_scheme')
        elif 'HTTP_X_FORWARDED_SCHEME' in environ:
            environ['wsgi.url_scheme'] = environ.pop('HTTP_X_FORWARDED_SCHEME')
        elif 'HTTP_X_FORWARDED_PROTO' in environ:
            environ['wsgi.url_scheme'] = environ.pop('HTTP_X_FORWARDED_PROTO')
        elif 'HTTP_X_FORWARDED_PROTOCOL' in environ:
            environ['wsgi.url_scheme'] = environ.pop('HTTP_X_FORWARDED_PROTOCOL')

    def __call__(self, environ, start_response):
        self._rewrite(environ)
        return self.app(environ, start_response)


def get_imperative_config(package):
    resolver = DottedNameResolver(package)
    try:
        return resolver.resolve('.application:configure_karl')
    except ImportError:
        return None


def is_normal_mode(registry):
    return registry.settings.get('mode', 'NORMAL').upper() == 'NORMAL'


def readonly(request, response):
    """
    This is a commit veto hook for use with pyramid_tm, which always vetos the
    commit (aborts the transaction).  It is intended to be used in conjunction
    with read-only mode to prevent ReadOnly errors--attempts to modify the
    database will be quietly ignored.  Use by setting `tm.commit_veto` to
    `karl.application.readonly` in `etc/karl.ini`.
    """
    return True
