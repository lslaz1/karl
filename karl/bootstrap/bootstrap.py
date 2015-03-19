import sys
import transaction
from zope.component import queryUtility

from pyramid.traversal import resource_path
from pyramid import testing
from repoze.workflow import get_workflow
from repoze.lemonade.content import create_content

from karl.bootstrap.interfaces import IInitialData
from karl.bootstrap.data import DefaultInitialData
from karl.models.contentfeeds import SiteEvents
from karl.models.interfaces import IProfile
from karl.models.site import Site
from karl.views.community import AddCommunityFormController
from pyramid.interfaces import IAuthenticationPolicy
from pyramid.threadlocal import get_current_registry


def populate(root, do_transaction_begin=True, request=None):
    if do_transaction_begin:
        transaction.begin()

    data = queryUtility(IInitialData, default=DefaultInitialData())
    site = root['site'] = Site()
    site.__acl__ = data.site_acl
    site.events = SiteEvents()
    if request:
        request.context = site

    # If a catalog database exists and does not already contain a catalog,
    # put the site-wide catalog in the catalog database.
    main_conn = root._p_jar
    try:
        catalog_conn = main_conn.get_connection('catalog')
    except KeyError:
        # No catalog connection defined.  Put the catalog in the
        # main database.
        pass
    else:
        catalog_root = catalog_conn.root()
        if 'catalog' not in catalog_root:
            catalog_root['catalog'] = site.catalog
            catalog_conn.add(site.catalog)
            main_conn.add(site)

    # the ZODB root isn't a Folder, so it doesn't send events that
    # would cause the root Site to be indexed
    docid = site.catalog.document_map.add(resource_path(site))
    site.catalog.index_doc(docid, site)
    site.docid = docid

    # the staff_acl is the ACL used as a basis for "public" resources
    site.staff_acl = data.staff_acl

    site['profiles'].__acl__ = data.profiles_acl

    site.moderator_principals = data.moderator_principals
    site.member_principals = data.member_principals
    site.guest_principals = data.guest_principals

    profiles = site['profiles']

    users = site.users

    for login, firstname, lastname, email, groups in data.users_and_groups:
        users.add(login, login, login, groups)
        profile = profiles[login] = create_content(IProfile,
                                                   firstname=firstname,
                                                   lastname=lastname,
                                                   email=email)
        workflow = get_workflow(IProfile, 'security', profiles)
        if workflow is not None:
            workflow.initialize(profile)

    # tool factory wants a dummy request
    COMMUNIITY_INCLUDED_TOOLS = data.community_tools
    class FauxPost(dict):
        def getall(self, key):
            return self.get(key, ())

    reg = get_current_registry()
    auth = reg.queryUtility(IAuthenticationPolicy)
    if hasattr(auth, '_policies'):
        auth = auth._policies[0]

    request = testing.DummyRequest(context=site)
    request.environ.update({
        'HTTP_HOST': 'localhost:8080',
        'karl.identity': {
            'id': 'admin',
            'groups': data.admin_groups
        }
    })
    cookies = auth.remember(request, 'admin')
    name, value = cookies[0][1].split(';')[0].split('=')
    request.cookies[name] = value

    # Create a Default community
    request.POST = FauxPost(request.POST)
    converted = {}
    converted['title'] = 'default'
    converted['description'] = 'Created by startup script'
    converted['text'] = '<p>Default <em>values</em> in here.</p>'
    converted['security_state'] = 'public'
    converted['tags'] = ''
    converted['tools'] = COMMUNIITY_INCLUDED_TOOLS

    communities = site['communities']
    add_community = AddCommunityFormController(communities, request)
    add_community.handle_submit(converted)
    communities['default'].title = 'Default Community'

    bootstrap_evolution(root)


def bootstrap_evolution(root):
    from zope.component import getUtilitiesFor
    from repoze.evolution import IEvolutionManager
    for pkg_name, factory in getUtilitiesFor(IEvolutionManager):
        __import__(pkg_name)
        package = sys.modules[pkg_name]
        manager = factory(root, pkg_name, package.VERSION)
        # when we do start_over, we unconditionally set the database's
        # version number to the current code number
        manager._set_db_version(package.VERSION)
