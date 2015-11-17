from __future__ import with_statement

import codecs
from cStringIO import StringIO
import csv
from _csv import Error
from repoze.postoffice.message import Message
import hashlib
import os
import re
import time
import transaction
from paste.fileapp import FileApp
from pyramid.response import Response
from pyramid.httpexceptions import HTTPFound
from datetime import datetime

from zope.component import getUtility

from persistent.list import PersistentList
from persistent.mapping import PersistentMapping

from pyramid.renderers import get_renderer
from pyramid.exceptions import NotFound
from pyramid.security import authenticated_userid
from pyramid.security import has_permission
from pyramid.traversal import find_resource
from pyramid.traversal import resource_path
from pyramid.url import resource_url
from repoze.lemonade.content import create_content
from repoze.postoffice.queue import open_queue
from repoze.sendmail.interfaces import IMailDelivery
from repoze.workflow import get_workflow

from karl.content.interfaces import IBlogEntry
from karl.content.interfaces import ICalendarEvent
from karl.content.interfaces import IWikiPage
from karl.models.interfaces import ICatalogSearch
from karl.models.interfaces import ICommunity
from karl.models.interfaces import ICommunityContent
from karl.models.interfaces import IInvitation
from karl.models.interfaces import ISiteInvitation
from karl.models.interfaces import IProfile
from karl.models.interfaces import DEFAULT_HOME_BEHAVIOR_OPTIONS
from karl.models.adapters import TIMEAGO_FORMAT
from karl.models.profile import Profile
from karl.security.policy import ADMINISTER
from karl.utilities.converters.interfaces import IConverter
from karl.utilities.rename_user import rename_user
from karl.utilities.interfaces import IRandomId
from karl.utilities.mailer import ThreadedGeneratorMailDelivery

from karl.registration import get_access_request_fields

from karl.utils import asbool
from karl.utils import find_communities
from karl.utils import find_community
from karl.utils import find_profiles
from karl.utils import find_site
from karl.utils import find_users
from karl.utils import get_setting
from karl.utils import get_config_setting
from karl.utils import create_message
from karl.views.api import TemplateAPI
from karl.views.utils import make_unique_name
from karl.views.batch import get_fileline_batch
from karl.views.forms import widgets as karlwidgets

import schemaish
import formish
from validatish import validator


class AdminTemplateAPI(TemplateAPI):

    def __init__(self, context, request, page_title=None):
        super(AdminTemplateAPI, self).__init__(context, request, page_title)
        settings = request.registry.settings
        syslog_view = get_config_setting('syslog_view', None)
        self.syslog_view_enabled = syslog_view is not None
        self.has_logs = not not get_config_setting('logs_view', None)
        self.redislog = asbool(settings.get('redislog', 'False'))
        statistics_folder = get_config_setting('statistics_folder', None)
        if statistics_folder is not None and os.path.exists(statistics_folder):
            csv_files = [fn for fn in os.listdir(statistics_folder)
                         if fn.endswith('.csv')]
            self.statistics_view_enabled = not not csv_files
        else:
            self.statistics_view_enabled = False

        self.quarantine_url = ('%s/po_quarantine.html' %
                               request.application_url)

        site = find_site(context)
        if 'offices' in site:
            self.offices_url = resource_url(site['offices'], request)
        else:
            self.offices_url = None

        self.has_mailin = (
            get_config_setting('zodbconn.uri.postoffice') and
            get_config_setting('postoffice.queue'))


def _menu_macro():
    return get_renderer(
        'templates/admin/menu.pt').implementation().macros['menu']


def admin_view(context, request):
    return dict(
        api=AdminTemplateAPI(context, request, 'Admin UI'),
        menu=_menu_macro(),
    )


def _content_selection_widget():
    return get_renderer(
        'templates/admin/content_select.pt').implementation().macros['widget']


def _content_selection_grid():
    return get_renderer(
        'templates/admin/content_select.pt').implementation().macros['grid']


def _format_date(d):
    return d.strftime("%m/%d/%Y %H:%M")


def _populate_content_selection_widget(context, request):
    """
    Returns a dict of parameters to be passed to the template that includes
    the content selection widget.
    """
    # Get communities list
    search = ICatalogSearch(context)
    count, docids, resolver = search(
        interfaces=[ICommunity],
        sort_index='title'
    )
    communities = []
    for docid in docids:
        community = resolver(docid)
        communities.append(dict(
            path=resource_path(community),
            title=community.title,
        ))

    return dict(
        communities=communities,
        title_contains=request.params.get('title_contains', None),
        selected_community=request.params.get('community', None),
    )


def _grid_item(item, request):
    creator_name, creator_url = 'Unknown', None
    profiles = find_profiles(item)
    creator = getattr(item, 'creator', None)
    if creator is not None and creator in profiles:
        profile = profiles[creator]
        creator_name = profile.title
        creator_url = resource_url(profile, request)

    return dict(
        path=resource_path(item),
        url=resource_url(item, request),
        title=item.title,
        modified=_format_date(item.modified),
        creator_name=creator_name,
        creator_url=creator_url,
    )


def _get_filtered_content(context, request, interfaces=None):
    if interfaces is None:
        interfaces = [ICommunityContent]
    search = ICatalogSearch(context)
    search_terms = dict(
        interfaces={'query': interfaces, 'operator': 'or'},
    )

    community = request.params.get('community', '_any')
    if community != '_any':
        search_terms['path'] = community

    title_contains = request.params.get('title_contains', '')
    if title_contains:
        title_contains = title_contains.lower()
        search_terms['texts'] = title_contains

    if community == '_any' and not title_contains:
        # Avoid retrieving entire site
        return []

    items = []
    count, docids, resolver = search(**search_terms)
    for docid in docids:
        item = resolver(docid)
        if (title_contains and title_contains not in
                getattr(item, 'title', '').lower()):
            continue
        items.append(_grid_item(item, request))

        # Try not to run out of memory
        if hasattr(item, '_p_deactivate'):
            item._p_deactivate()

    items.sort(key=lambda x: x['path'])
    return items


def delete_content_view(context, request):
    api = AdminTemplateAPI(context, request, 'Admin UI: Delete Content')
    filtered_content = []

    if 'filter_content' in request.params:
        filtered_content = _get_filtered_content(context, request)
        if not filtered_content:
            api.status_message = 'No content matches your query.'

    if 'delete_content' in request.params:
        paths = request.params.getall('selected_content')
        if paths:
            for path in paths:
                try:
                    content = find_resource(context, path)
                    del content.__parent__[content.__name__]
                except KeyError:
                    # Thrown by find_resource if we've already deleted an
                    # ancestor of this node.  Can safely ignore becuase child
                    # node has been deleted along with ancestor.
                    pass

            if len(paths) == 1:
                status_message = 'Deleted one content item.'
            else:
                status_message = 'Deleted %d content items.' % len(paths)

            redirect_to = resource_url(
                context, request, request.view_name,
                query=dict(status_message=status_message)
            )
            return HTTPFound(location=redirect_to)

    parms = dict(
        api=api,
        menu=_menu_macro(),
        content_select_widget=_content_selection_widget(),
        content_select_grid=_content_selection_grid(),
        filtered_content=filtered_content,
    )
    parms.update(_populate_content_selection_widget(context, request))
    return parms


class _DstNotFound(Exception):
    pass


def _find_dst_container(src_obj, dst_community):
    """
    Given a source object and a destination community, figures out the
    container insider the destination community where source object can be
    moved to.  For example, if source object is a blog entry in community
    `foo` (/communities/foo/blog/entry1) and we want to move it to the `bar`
    community, this will take the relative path of the source object from its
    community and attempt to find analogous containers inside of the
    destination community.  In this example, the relative container path is
    'blog', so we the destination container is /communities/bar/blog.'
    """
    src_container_path = resource_path(src_obj.__parent__)
    src_community_path = resource_path(find_community(src_obj))
    rel_container_path = src_container_path[len(src_community_path):]
    dst_container = dst_community
    for node_name in filter(None, rel_container_path.split('/')):
        dst_container = dst_container.get(node_name, None)
        if dst_container is None:
            raise _DstNotFound(
                'Path does not exist in destination community: %s' %
                resource_path(dst_community) + rel_container_path
            )
    return dst_container


def move_content_view(context, request):
    """
    Move content from one community to another.  Only blog entries supported
    for now.  May or may not eventually expand to other content types.
    """
    api = AdminTemplateAPI(context, request, 'Admin UI: Move Content')
    filtered_content = []

    if 'filter_content' in request.params:
        # We're limiting ourselves to content that always lives in the same
        # place in each community, ie /blog, /calendar, /wiki, etc, so that
        # we can be pretty sure we can figure out where inside the destination
        # community we should move it to.
        filtered_content = _get_filtered_content(
            context, request, [IBlogEntry, IWikiPage, ICalendarEvent])
        if not filtered_content:
            api.error_message = 'No content matches your query.'

    if 'move_content' in request.params:
        to_community = request.params.get('to_community', '')
        if not to_community:
            api.error_message = 'Please specify destination community.'
        else:
            try:
                paths = request.params.getall('selected_content')
                dst_community = find_resource(context, to_community)
                for path in paths:
                    obj = find_resource(context, path)
                    dst_container = _find_dst_container(obj, dst_community)
                    name = make_unique_name(dst_container, obj.__name__)
                    del obj.__parent__[obj.__name__]
                    dst_container[name] = obj

                if len(paths) == 1:
                    status_message = 'Moved one content item.'
                else:
                    status_message = 'Moved %d content items.' % len(paths)

                redirect_to = resource_url(
                    context, request, request.view_name,
                    query=dict(status_message=status_message)
                )
                return HTTPFound(location=redirect_to)
            except _DstNotFound, error:
                api.error_message = str(error)

    parms = dict(
        api=api,
        menu=_menu_macro(),
        content_select_widget=_content_selection_widget(),
        content_select_grid=_content_selection_grid(),
        filtered_content=filtered_content,
    )
    parms.update(_populate_content_selection_widget(context, request))
    return parms


def site_announcement_view(context, request):
    """
    Edit the text of the site announcement, which will be displayed on
    every page for every user of the site.
    """
    site = find_site(context)
    if ('submit-site-announcement' in request.params) or ('submit' in request.params):
        annc = request.params.get('site-announcement-input', '').strip()
        if annc:
            # we only take the content of the first <p> tag, with
            # the <p> tags stripped
            paramatcher = re.compile('<[pP]\\b[^>]*>(.*?)</[pP]>')
            match = paramatcher.search(annc)
            if match is not None:
                anncontent = match.groups()[0]
            if not hasattr(site, 'site_announcements'):
                site.site_announcements = PersistentList()
            annc = PersistentMapping()
            annc["content"] = anncontent
            annc["added"] = datetime.now()
            annc["hash"] = hashlib.md5("{}{}".format(
                anncontent, annc["added"]).encode()).hexdigest()
            site.site_announcements.insert(0, annc)

    if 'remove-site-announcement' in request.params:
        hsh = request.params['remove-site-announcement']
        try:
            for item in site.site_announcements:
                if item['hash'] == hsh:
                    site.site_announcements.remove(item)
                    break
            # site.site_announcements.pop(int(idx))
        except ValueError:
            pass
        except IndexError:
            pass
    api = AdminTemplateAPI(context, request, 'Admin UI: Site Announcement')
    announcements = getattr(site, 'site_announcements', PersistentList())
    return dict(
        api=api,
        site_announcements=announcements,
        menu=_menu_macro()
        )


def _send_email(mailer, message, addressed_to):
    for addressed in addressed_to:
        # clear headers for sending multiple times...
        for header in ['To', 'X-Actually-From', 'X-Actually-To']:
            if header in message:
                del message[header]
        message['To'] = '%s <%s>' % (addressed['name'], addressed['email'])
        mailer.send([addressed['email']], message)


class EmailUsersView(object):
    # The groups are a pretty obvious customization point, so we make this view
    # a class so that customization packages can subclass this and override
    # the groups.

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def send_email(self, subject, body, addressed_to, from_email):
        message = create_message(self.request, subject, body, from_email)
        if get_config_setting('use_threads_to_send_email', False) in (True, 'true', 'True'):  # noqa
            mailer = ThreadedGeneratorMailDelivery()
            mailer.sendGenerator(
                _send_email, mailer, message, addressed_to)
        else:
            mailer = getUtility(IMailDelivery)
            _send_email(mailer, message, addressed_to)

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Send Email')
        admin_email = get_setting(context, 'admin_email')
        system_name = get_setting(context, 'title')
        profiles = find_profiles(context)
        admin = profiles[authenticated_userid(request)]
        from_emails = [
            ('admin', '%s Administrator <%s>' % (system_name, admin_email)),
            ('self', '%s <%s>' % (admin.title, admin.email))
        ]
        all_groups = self.context.settings.get('email_groups', PersistentMapping())
        to_groups = [
            ('none', 'None'),
            ('group.KarlStaff', 'Staff'),
            ('', 'Everyone'),
        ]
        for (k, v) in all_groups.iteritems():
            to_groups.append(('group-' + k, k))

        if 'send_email' in request.params or 'submit' in request.params:
            from_email = from_emails[0][1]
            if request.params['from_email'] == 'self':
                from_email = from_emails[1][1]
            group = request.params['to_group']
            users = find_users(context)
            search = ICatalogSearch(context)
            count, docids, resolver = search(interfaces=[IProfile])
            n = 0
            addressed_to = []
            if group == 'group.KarlStaff' or group == '':
                for docid in docids:
                    profile = resolver(docid)
                    if getattr(profile, 'security_state', None) == 'inactive':
                        continue
                    userid = profile.__name__
                    if group and not users.member_of_group(userid, group):
                        continue
                    addressed_to.append({
                        'name': profile.title,
                        'email': profile.email
                    })
                    n += 1
            if group.startswith('group-'):
                group_key = group.replace('group-', '')
                alladdresses = all_groups.get(group_key, [])
                for entry in alladdresses:
                    addressed_to.append({
                        'name': '',
                        'email': entry.get('email', '')
                    })
                    n += 1
            # parse additional to email addresses
            if request.params['more_to']:
                more_to = request.params['more_to'].split(",")
                for to_email in more_to:
                    emailparts = to_email.split("@")
                    if len(emailparts) != 2:
                        continue
                    # could validate email more here
                    addressed_to.append({
                        'name': emailparts[0],
                        'email': to_email
                    })
                    n += 1
            if n == 0 or request.params['text'] == '':
                if n == 0:
                    api.status_message = "At least 1 recipient is required"
                else:
                    api.status_message = "Message Body is required"
                return dict(
                    api=api,
                    menu=_menu_macro(),
                    to_groups=to_groups,
                    to_grp_value=group,
                    from_emails=from_emails,
                    from_email_value=from_email,
                    msg_subject=request.params['subject'],
                    msg_body=request.params['text'],
                    more_to=request.params['more_to'],
                )
            self.send_email(
                request.params['subject'], request.params['text'],
                addressed_to, from_email)

            status_message = "Sent message to %d users." % n
            if has_permission(ADMINISTER, context, request):
                redirect_to = resource_url(
                    context, request, 'admin.html',
                    query=dict(status_message=status_message))
            else:
                redirect_to = resource_url(
                    find_communities(context), request, 'all_communities.html',
                    query=dict(status_message=status_message))

            return HTTPFound(location=redirect_to)

        return dict(
            api=api,
            menu=_menu_macro(),
            to_groups=to_groups,
            to_grp_value='none',
            from_emails=from_emails,
            from_email_value='admin',
            msg_subject='',
            msg_body='',
            more_to='',
        )


def getemailusers(profiles, selected_members):
    peoplelist = []
    excludefirsts = ['former', 'system']
    for prof in profiles:
        profile = profiles.get(prof, None)
        if profile is not None:
            if profile.firstname in (excludefirsts):
                continue
            isselected = False
            if prof in selected_members:
                isselected = True
            peoplelist.append({'name': profile.firstname + ' ' + profile.lastname,
                               'login': prof,
                               'selected': isselected})

    return peoplelist


def process_email_groups(request, profiles):
    emails = request.params['email_address'].split('\n')
    email_list = []
    for email in emails:
        if email == u'\r' or email == u'':
            continue
        email_list.append({'name': '', 'email': email, 'member_login': ''})

    # process existing members email addresses
    if 'memberemails' in request.params:
        memberemails = request.params.getall('memberemails')
        for tmplogin in memberemails:
            person = profiles.get(tmplogin, None)
            if person is not None:
                email_list.append({'name': person.firstname, 'email': person.email,
                                   'member_login': tmplogin})

    return email_list


class AddEmailGroup(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Add Email Group')

        # get list of users
        profiles = find_profiles(context)
        peoplelist = getemailusers(profiles, [])

        if 'save' in request.params or 'submit' in request.params:
            all_groups = self.context.settings.get('email_groups', PersistentMapping())
            group_name = request.params['group_name']
            email_list = process_email_groups(request, profiles)
            all_groups[group_name] = email_list
            self.context.settings['email_groups'] = all_groups

            status_message = 'Email Group "' + group_name + '" has been created'
            if has_permission(ADMINISTER, context, request):
                redirect_to = resource_url(
                    context, request, 'email_groups.html',
                    query=dict(status_message=status_message))
            else:
                redirect_to = resource_url(
                    find_communities(context), request, 'all_communities.html',
                    query=dict(status_message=status_message))

            return HTTPFound(location=redirect_to)

        return dict(
            api=api,
            actions=[],
            menu=_menu_macro(),
            group_name='',
            email_address='',
            peoplelist=peoplelist
        )


class EditEmailGroup(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Edit Email Group')

        actions = []
        thisgroup = request.subpath
        thisgroup = thisgroup[0]
        actions.append(
            ('Delete',
             request.resource_url(context, 'del_email_group' + u'/' + thisgroup)),
            )
        all_groups = self.context.settings.get('email_groups', PersistentMapping())
        alladdresses = all_groups.get(thisgroup, [])

        display_email = ''
        selected_members = []
        for entry in alladdresses:
            tmpemail = entry.get('email', '')
            tmplogin = entry.get('member_login', '')
            if tmplogin == '':
                display_email = display_email + tmpemail + "\n"
            else:
                selected_members.append(tmplogin)

        profiles = find_profiles(context)
        peoplelist = getemailusers(profiles, selected_members)
        if 'save' in request.params or 'submit' in request.params:
            group_name = request.params['group_name']

            email_list = process_email_groups(request, profiles)
            all_groups[group_name] = email_list
            self.context.settings['email_groups'] = all_groups

            status_message = 'Email Group "'\
                + group_name + '" successfully modified'
            if has_permission(ADMINISTER, context, request):
                redirect_to = resource_url(
                    context, request, 'email_groups.html',
                    query=dict(status_message=status_message))
            else:
                redirect_to = resource_url(
                    find_communities(context), request, 'all_communities.html',
                    query=dict(status_message=status_message))

            return HTTPFound(location=redirect_to)

        return dict(
            api=api,
            actions=actions,
            menu=_menu_macro(),
            group_name=thisgroup,
            email_address=display_email,
            peoplelist=peoplelist,
            data={'id', 'admin'}
        )


class DeleteEmailGroup(object):
    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request

        thisgroup = request.subpath
        thisgroup = thisgroup[0]
        all_groups = self.context.settings.get('email_groups', PersistentMapping())
        del all_groups[thisgroup]
        self.context.settings['email_groups'] = all_groups
        redirect_to = resource_url(
            context, request, 'email_groups.html',
            query=dict(status_message='Email group "' + thisgroup + '" has been deleted'))
        return HTTPFound(location=redirect_to)


class EmailGroupsView(object):
    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Email Groups')

        actions = []
        actions.append(
            ('Add Email Group',
             request.resource_url(context, 'add_email_group.html')),
            )

        if 'email_groups' in self.context.settings:
            email_groups = self.context.settings.get('email_groups')
        else:
            email_groups = {}
            self.context.settings['email_groups'] = email_groups

        return dict(
            api=api,
            actions=actions,
            menu=_menu_macro(),
            email_groups=email_groups,
        )


class EmailTemplateView(object):
    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Email Templates')

        actions = []
        actions.append(
            ('Add Email Template',
             request.resource_url(context, 'add_email_template.html')),
            )

        template_names = []
        for e_t in self.context.email_templates:
            template_names.append(e_t)

        return dict(
            api=api,
            actions=actions,
            menu=_menu_macro(),
            email_templates=template_names
        )


class AddEmailTemplate(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Add Email Group')

        # get list of users
        profiles = find_profiles(context)
        peoplelist = getemailusers(profiles, [])

        if 'save' in request.params or 'submit' in request.params:
            selected_list = []
            memberemails = request.params.getall('memberemails')
            for tmplogin in memberemails:
                selected_list.append(tmplogin)
            template_name = request.params['template_name']
            template_body = request.params['text']
            sendtoadmins = request.params.get('sendtoadmins', 'no')
            sendtouser = request.params.get('sendtouser', 'no')
            self.context.email_templates[template_name] = {'body': template_body,
                                                           'template_name': template_name,
                                                           'selected_list': selected_list,
                                                           'sendtouser': sendtouser,
                                                           'sendtoadmins': sendtoadmins}

            status_message = 'Email Template "' + template_name + '" has been created'
            if has_permission(ADMINISTER, context, request):
                redirect_to = resource_url(
                    context, request, 'email_templates.html',
                    query=dict(status_message=status_message))
            else:
                redirect_to = resource_url(
                    find_communities(context), request, 'all_communities.html',
                    query=dict(status_message=status_message))

            return HTTPFound(location=redirect_to)

        return dict(
            api=api,
            actions=[],
            menu=_menu_macro(),
            template_name='',
            template_body='',
            template_subject='',
            sendtouser='no',
            sendtoadmins='no',
            peoplelist=peoplelist
        )


class EditEmailTemplate(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Edit Email Group')

        actions = []
        thistemplate = request.subpath
        thistemplate = thistemplate[0]

        actions.append(
            ('Delete',
             request.resource_url(context, 'del_email_template' + u'/' + thistemplate)),
            )
        edit_template = self.context.email_templates.get(thistemplate, {})

        profiles = find_profiles(context)
        peoplelist = getemailusers(profiles, edit_template.get('selected_list', []))
        if 'save' in request.params or 'submit' in request.params:
            selected_list = []
            memberemails = request.params.getall('memberemails')
            for tmplogin in memberemails:
                selected_list.append(tmplogin)
            sendtoadmins = request.params.get('sendtoadmins', 'no')
            sendtouser = request.params.get('sendtouser', 'no')
            template_name = request.params['template_name']
            subject = request.params['template_subject']
            template_body = request.params['text']
            self.context.email_templates[template_name] = {'body': template_body,
                                                           'template_name': template_name,
                                                           'selected_list': selected_list,
                                                           'subject': subject,
                                                           'sendtouser': sendtouser,
                                                           'sendtoadmins': sendtoadmins}
            # delete old record if key is changing
            if thistemplate != template_name:
                del self.context.email_templates[thistemplate]

            status_message = 'Email Template "' + template_name + '" has been successfully modified'
            if has_permission(ADMINISTER, context, request):
                redirect_to = resource_url(
                    context, request, 'email_templates.html',
                    query=dict(status_message=status_message))
            else:
                redirect_to = resource_url(
                    find_communities(context), request, 'all_communities.html',
                    query=dict(status_message=status_message))

            return HTTPFound(location=redirect_to)

        return dict(
            api=api,
            actions=actions,
            menu=_menu_macro(),
            template_name=thistemplate,
            template_body=edit_template.get('body', ''),
            template_subject=edit_template.get('subject', ''),
            sendtouser=edit_template.get('sendtouser', 'no'),
            sendtoadmins=edit_template.get('sendtoadmins', 'no'),
            peoplelist=peoplelist
        )


class DeleteEmailTemplate(object):
    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context, request = self.context, self.request

        thistempl = request.subpath
        thistempl = thistempl[0]
        if thistempl in self.context.email_templates:
            del self.context.email_templates[thistempl]
        redirect_to = resource_url(
            context, request, 'email_templates.html',
            query=dict(status_message='Email template "' + thistempl + '" has been deleted'))
        return HTTPFound(location=redirect_to)


def syslog_view(context, request):
    syslog_path = get_config_setting('syslog_view')
    instances = get_config_setting('syslog_view_instances', ['karl'])
    filter_instance = request.params.get('instance', '_any')
    if filter_instance == '_any':
        filter_instances = instances
    else:
        filter_instances = [filter_instance]

    def line_filter(line):
        try:
            month, day, time, host, instance, message = line.split(None, 5)
        except ValueError:
            # Ignore lines that don't fit the format
            return None

        if instance not in filter_instances:
            return None

        return line

    if syslog_path:
        syslog = codecs.open(syslog_path, encoding='utf-8',
                             errors='replace')
    else:
        syslog = StringIO()

    batch_info = get_fileline_batch(syslog, context, request,
                                    line_filter=line_filter, backwards=True)

    return dict(
        api=AdminTemplateAPI(context, request),
        menu=_menu_macro(),
        instances=instances,
        instance=filter_instance,
        batch_info=batch_info,
    )


def logs_view(context, request):
    log_paths = get_config_setting('logs_view')
    if len(log_paths) == 1:
        # Only one log file, just view that
        log = log_paths[0]

    else:
        # Make user pick a log file
        log = request.params.get('log', None)

        # Don't let users view arbitrary files on the filesystem
        if log not in log_paths:
            log = None

    if log is not None and os.path.exists(log):
        lines = codecs.open(log, encoding='utf-8',
                            errors='replace').readlines()
    else:
        lines = []

    return dict(
        api=AdminTemplateAPI(context, request),
        menu=_menu_macro(),
        logs=log_paths,
        log=log,
        lines=lines,
    )


def statistics_view(context, request):
    statistics_folder = get_config_setting('statistics_folder')
    csv_files = [fn for fn in os.listdir(statistics_folder)
                 if fn.endswith('.csv')]
    return dict(
        api=AdminTemplateAPI(context, request),
        menu=_menu_macro(),
        csv_files=csv_files
    )


def statistics_csv_view(request):
    statistics_folder = get_config_setting('statistics_folder')
    csv_file = request.matchdict.get('csv_file')
    if not csv_file.endswith('.csv'):
        raise NotFound()

    path = os.path.join(statistics_folder, csv_file)
    if not os.path.exists(path):
        raise NotFound()

    return request.get_response(FileApp(path).get)


class UploadUsersView(object):
    rename_user = rename_user

    required_fields = [
        'username',
        'email',
        'firstname',
        'lastname',
    ]

    allowed_fields = required_fields + [
        'phone',
        'extension',
        'department',
        'position',
        'organization',
        'location',
        'country',
        'website',
        'languages',
        'office',
        'room_no',
        'biography',
        'home_path',
        'login',
        'groups',
        'password',
        'sha_password',
    ]

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        context = self.context
        request = self.request

        errors = []
        messages = []

        # Handle CSV upload
        field = request.params.get('csv', None)
        if hasattr(field, 'file'):
            reactivate = request.params.get('reactivate') == 'true'
            reader = csv.DictReader(field.file)
            try:
                rows = list(reader)
            except Error, e:
                errors.append("Malformed CSV: %s" % e[0])

            # Make sure we have required fields
            if not errors:
                fieldnames = rows[0].keys()
                if None in fieldnames:
                    errors.append(
                        "Malformed CSV: line 2 does not match header."
                    )
                else:
                    for required_field in self.required_fields:
                        if required_field not in fieldnames:
                            errors.append("Missing required field: %s" %
                                          required_field)
                    if (not ('password' in fieldnames or
                             'sha_password' in fieldnames)):
                        errors.append('Must supply either password or '
                                      'sha_password field.')

                    # Restrict to allowed fields
                    allowed_fields = self.allowed_fields
                    for fieldname in fieldnames:
                        if fieldname not in allowed_fields:
                            errors.append("Unrecognized field: %s" % fieldname)

            # Add users
            if not errors:
                search = ICatalogSearch(context)
                profiles = find_profiles(context)
                users = find_users(context)

                n_added = 0
                for i, row in enumerate(rows):
                    if None in row or None in row.values():
                        errors.append(
                            "Malformed CSV: line %d does not match header." %
                            (i+2))
                        break
                    added_users, row_messages, row_errors = (
                        self._add_user_csv_row(search, profiles, users, row,
                                               reactivate, i)
                    )
                    n_added += added_users
                    messages += row_messages
                    errors += row_errors

                if not errors:
                    messages.append("Created %d users." % n_added)

        if errors:
            transaction.doom()

        api = AdminTemplateAPI(context, request, 'Admin UI: Upload Users')
        api.error_message = '\n'.join(errors)
        api.status_message = '\n'.join(messages)

        return dict(
            api=api,
            menu=_menu_macro(),
            required_fields=self.required_fields,
            allowed_fields=self.allowed_fields,
        )

    def _add_user_csv_row(self, search, profiles, users, row, reactivate, i):
        errors = []
        messages = []

        username = row.pop('username')
        login = row.pop('login', username)
        if not username:
            errors.append(
                "Malformed CSV: line %d has an empty username." %
                (i+2))

        email = row['email']
        if not email:
            errors.append(
                'Malformed CSV: line %d has an empty email address.' % (i+2)
            )

        if errors:
            return 0, messages, errors

        website = row.pop('website', None)
        if website is not None:
            row['websites'] = website.strip().split()

        profile = profiles.get(username)
        skip = False
        if (users.get_by_id(username) is not None or
                (profile is not None and profile.security_state != 'inactive')):
            messages.append(
                "Skipping user: %s: User already exists." %
                username
            )
            skip = True
        elif users.get_by_login(login):
            messages.append(
                "Skipping user: %s: User already exists with "
                "login: %s" % (username, login)
            )
            skip = True

        if skip:
            return 0, messages, errors

        merge_profile = None
        count, docids, resolver = search(email=email)
        if count > 1:
            errors.append(
                'Multiple users already exist with email '
                'address: %s' % email
            )
        elif count == 1:
            previous = resolver(iter(docids).next())
            if IInvitation.providedBy(previous):
                # This user was previously invited to join a community.  Remove
                # the invitation and carry on
                del previous.__parent__[previous.__name__]
            else:
                merge_profile = resolver(docids[0])
                if merge_profile.security_state != 'inactive':
                    errors.append(
                        'An active user already exists with email '
                        'address: %s.' % email
                    )
                elif not reactivate:
                    errors.append(
                        'A previously deactivated user exists with '
                        'email address: %s.  Consider checking the '
                        '"Reactivate user" checkbox to reactivate '
                        'the user.' % email
                    )

                if merge_profile.__name__ == username:
                    merge_profile = None

        if profile is None:
            profile = profiles.get(username)
            if profile is not None and not reactivate:
                errors.append(
                    'A previously deactivated user exists with username: %s.  '
                    'Consider checking the "Reactivate user" checkbox to '
                    'reactivate the user.' % username
                )

        if errors:
            return 0, messages, errors

        groups = row.pop('groups', '')
        groups = set(groups.split())
        if 'sha_password' in row:
            users.add(username, login, row.pop('sha_password'), groups)
        else:
            users.add(username, login, row.pop('password'), groups)
        decoded = {}
        for k, v in row.items():
            if isinstance(v, str):
                try:
                    v = v.decode('utf8')
                except UnicodeDecodeError:
                    v = v.decode('latin1')
            decoded[k] = v
        if profile is None:
            profile = create_content(IProfile, **decoded)
            profiles[username] = profile
            workflow = get_workflow(IProfile, 'security', profile)
            if workflow is not None:
                workflow.initialize(profile)
        else:
            messages.append('Reactivated %s.' % username)
            for k, v in decoded.items():
                setattr(profile, k, v)
            workflow = get_workflow(IProfile, 'security', profile)
            workflow.transition_to_state(profile, None, 'active')

        if merge_profile is not None:
            merge_messages = StringIO()
            self.rename_user(profile, merge_profile.__name__, username,
                             merge=True, out=merge_messages)
            messages += merge_messages.getvalue().split('\n')

        return 1, messages, errors


def _decode(s):
    """
    Convert to unicode, by hook or crook.
    """
    try:
        return s.decode('utf-8')
    except UnicodeDecodeError:
        # Will probably result in some junk characters but it's better than
        # nothing.
        return s.decode('latin-1')


def _get_redislog(registry):
    redislog = getattr(registry, 'redislog', None)
    if redislog:
        return redislog

    settings = registry.settings
    if not asbool(settings.get('redislog', 'False')):
        return

    redisconfig = dict([(k[9:], v) for k, v in settings.items()
                        if k.startswith('redislog.')])
    for intkey in ('port', 'db', 'expires'):
        if intkey in redisconfig:
            redisconfig[intkey] = int(intkey)

    from karl.redislog import RedisLog
    settings.redislog = redislog = RedisLog(**redisconfig)
    return redislog


def error_status_view(context, request):
    redislog = _get_redislog(request.registry)
    if not redislog:
        raise NotFound
    response = 'ERROR' if redislog.alarm() else 'OK'
    return Response(response, content_type='text/plain')


def redislog_view(context, request):
    redislog = _get_redislog(request.registry)
    if not redislog:
        raise NotFound

    if 'clear_alarm' in request.params:
        redislog.clear_alarm()
        query = request.params.copy()
        del query['clear_alarm']
        if query:
            kw = {'query': query}
        else:
            kw = {}
        return HTTPFound(location=request.resource_url(
            context, request.view_name, **kw))

    level = request.params.get('level')
    category = request.params.get('category')

    redis_levels = redislog.levels()
    if len(redis_levels) > 1:
        if category:
            level_params = {'category': category}
            urlkw = {'query': level_params}
        else:
            level_params = {}
            urlkw = {}
        levels = [{'name': 'All', 'current': not level,
                   'url': request.resource_url(
                       context, request.view_name, **urlkw)}]
        for choice in redis_levels:
            level_params['level'] = choice
            levels.append(
                {'name': choice,
                 'current': choice == level,
                 'url': request.resource_url(context, request.view_name,
                                             query=level_params)})
    else:
        levels = None

    redis_categories = redislog.categories()
    if len(redis_categories) > 1:
        if level:
            category_params = {'level': level}
            urlkw = {'query': category_params}
        else:
            category_params = {}
            urlkw = {}
        categories = [{'name': 'All', 'current': not category,
                       'url': request.resource_url(
                           context, request.view_name, **urlkw)}]
        for choice in redislog.categories():
            category_params['category'] = choice
            categories.append(
                {'name': choice,
                 'current': choice == category,
                 'url': request.resource_url(context, request.view_name,
                                             query=category_params)})
    else:
        categories = None

    log = [
        {'timestamp': time.asctime(time.localtime(entry.timestamp)),
         'level': entry.level,
         'category': entry.category,
         'hostname': getattr(entry, 'hostname', None),  # BBB?
         'summary': entry.message.split('\n')[0],
         'details': '%s\n\n%s' % (entry.message, entry.traceback)
                    if entry.traceback else entry.message}
        for entry in redislog.iterate(
            level=level, category=category, count=100)]

    clear_params = request.params.copy()
    clear_params['clear_alarm'] = '1'
    clear_alarm_url = request.resource_url(context, request.view_name,
                                           query=clear_params)
    return {
        'api': AdminTemplateAPI(context, request),
        'menu': _menu_macro(),
        'alarm': redislog.alarm(),
        'clear_alarm_url': clear_alarm_url,
        'levels': levels,
        'level': level,
        'categories': categories,
        'category': category,
        'log': log}


def _get_postoffice_queue(context):
    zodb_uri = get_config_setting('zodbconn.uri.postoffice')
    queue_name = get_config_setting('postoffice.queue')
    if zodb_uri and queue_name:
        db = context._p_jar.db().databases['postoffice']
        return open_queue(db, queue_name)
    return None, None


def postoffice_quarantine_view(request):
    """
    See messages in postoffice quarantine.
    """
    context = request.context
    queue, closer = _get_postoffice_queue(context)
    if queue is None:
        raise NotFound

    if request.params:
        for key in request.params.keys():
            if key.startswith('delete_'):
                message_id = key.split('_')[1]
                if message_id == 'all':
                    messages = [message for message, error in
                                queue.get_quarantined_messages()]
                    for message in messages:
                        queue.remove_from_quarantine(message)
                else:
                    queue.remove_from_quarantine(
                        queue.get_quarantined_message(message_id)
                    )
            elif key.startswith('requeue_'):
                message_id = key.split('_')[1]
                if message_id == 'all':
                    messages = [message for message, error in
                                queue.get_quarantined_messages()]
                    for message in messages:
                        queue.remove_from_quarantine(message)
                        queue.add(message)
                else:
                    message = queue.get_quarantined_message(message_id)
                    queue.remove_from_quarantine(message)
                    queue.add(message)
        closer.conn.transaction_manager.commit()
        return HTTPFound(
            location=resource_url(context, request, request.view_name)
        )

    messages = []
    for message, error in queue.get_quarantined_messages():
        po_id = message['X-Postoffice-Id']
        url = '%s/po_quarantine/%s' % (
            request.application_url, po_id
        )
        messages.append(
            dict(url=url, message_id=message['Message-Id'], po_id=po_id,
                 error=unicode(error, 'UTF-8'))
        )

    return dict(
        api=AdminTemplateAPI(context, request),
        menu=_menu_macro(),
        messages=messages
    )


def postoffice_quarantine_status_view(request):
    """
    Report status of quarantine.  If no messages are in quarantine, status is
    'OK', otherwise status is 'ERROR'.
    """
    queue, closer = _get_postoffice_queue(request.context)
    if queue is None:
        raise NotFound
    if queue.count_quarantined_messages() == 0:
        return Response('OK')
    return Response('ERROR')


def postoffice_quarantined_message_view(request):
    """
    View a message in the postoffice quarantine.
    """
    queue, closer = _get_postoffice_queue(request.context)
    if queue is None:
        raise NotFound
    id = request.matchdict.get('id')
    try:
        msg = queue.get_quarantined_message(id)
    except KeyError:
        raise NotFound
    return Response(body=msg.as_string(), content_type='text/plain')


def rename_or_merge_user_view(request, rename_user=rename_user):
    """
    Rename or merge users.
    """
    context = request.context
    api = AdminTemplateAPI(context, request, 'Admin UI: Rename or Merge Users')
    old_username = request.params.get('old_username')
    new_username = request.params.get('new_username')
    if old_username and new_username:
        merge = bool(request.params.get('merge'))
        rename_messages = StringIO()
        try:
            rename_user(context, old_username, new_username, merge=merge,
                        out=rename_messages)
            api.status_message = rename_messages.getvalue()
        except ValueError, e:
            api.error_message = str(e)

    return dict(
        api=api,
        menu=_menu_macro()
    )


def debug_converters(request):
    converters = []
    for name, utility in sorted(request.registry.getUtilitiesFor(IConverter)):
        command = getattr(utility, 'depends_on', None) or 'n/a'
        converters.append({'name': name,
                           'command': command,
                           'available': utility.isAvailable(),
                           })
    api = AdminTemplateAPI(request.context, request,
                           'Admin UI: Debug Converters')
    return {'converters': converters,
            'environ': sorted(os.environ.items()),
            'api': api,
            'menu': _menu_macro(),
            }


def _send_invite(context, request, invitation):
    mailer = getUtility(IMailDelivery)
    body_template = get_renderer(
        'templates/admin/email_invite_new.pt').implementation()

    msg = Message()
    msg['From'] = '%s <%s>' % (
        get_setting(context, 'title'),
        get_setting(context, 'admin_email'))
    msg['To'] = invitation.email
    msg['Subject'] = 'Please join %s' % get_setting(context, 'title')
    body = body_template(
        system_name=get_setting(context, 'title'),
        invitation_url=resource_url(invitation.__parent__, request,
                                    invitation.__name__)
        )

    if isinstance(body, unicode):
        body = body.encode("UTF-8")

    msg.set_payload(body, "UTF-8")
    msg.set_type('text/html')
    mailer.send([invitation.email], msg)


def add_denial(context, requestor_email, requestor_name, reason, full_reason):
    previous_denails = context.denial_tracker.get(requestor_email, {})
    # get all denials for this user
    all_denials = previous_denails.get('all_denials', {})
    # add current denial
    all_denials[datetime.now()] = {'reason': reason,
                                   'reason_full': full_reason}
    context.denial_tracker[requestor_email] = {'all_denials': all_denials,
                                               'email:': requestor_email,
                                               'fullname': requestor_name}


class ReviewSiteInvitations(object):
    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.invitations = self.context['invitations']

    def __call__(self):
        messages = []
        if self.request.method == 'POST' and self.request.POST.get('form.submitted'):
            data = self.request.POST.dict_of_lists()

            for invite_id in data.get('delete', []):
                if invite_id in self.invitations:
                    invitation = self.invitations[invite_id]
                    messages.append("Approved: %s" % invitation.email)
                    del self.invitations[invite_id]

            for invite_id in data.get('resend', []):
                if invite_id in self.invitations:
                    invitation = self.invitations[invite_id]
                    invitation.created_on = datetime.utcnow()
                    _send_invite(self.context, self.request, invitation)
                    messages.append("Re-sent invite: %s" % invitation.email)
        api = AdminTemplateAPI(self.context, self.request)
        api.status_messages = messages

        return {
            'api': api,
            'page_title': 'Review Invitations',
            'format_date': lambda date: date.strftime(TIMEAGO_FORMAT),
            'menu': _menu_macro(),
            'invitations': reversed(sorted(
                self.invitations.values(), key=lambda r: r.created_on.isoformat())),
        }


class ReviewAccessRequest(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.random_id = getUtility(IRandomId)
        self.invitations = self.context['invitations']
        self.search = ICatalogSearch(self.context)

    def replace_keywords(self, in_replace_text, access_request):
        sys_name = get_setting(self.context, 'title')
        replace_text = in_replace_text.replace('{{requestor_email}}', access_request['email'])
        replace_text = replace_text.replace('{{requestor_name}}', access_request['fullname'])
        replace_text = replace_text.replace('{{system_name}}', sys_name)
        return replace_text

    def get_templ_msg(self, email, template_name, response_type):
        access_request = self.context.access_requests[email]
        e_template = self.context.email_templates.get(template_name, {})

        email_data = {}
        email_data['email'] = email
        email_data['from'] = get_setting(self.context, 'admin_email')
        if response_type == 'approve':
            invitation = self.get_invitation(email)
            invitation_url = resource_url(invitation.__parent__, self.request, invitation.__name__)
            body = e_template['body']
            body = body + u'''<p>Follow the link below to accept this invitation and to create your account.</p>

                            <p>
                              <a href=%s>%s</a>
                            </p>''' % (invitation_url, invitation_url)
            email_data['body'] = self.replace_keywords(body, access_request)
        else:
            email_data['body'] = self.replace_keywords(e_template['body'], access_request)
#         email_data['to'] = e_template['selected_list']
        email_to = []
        if e_template.get('sendtouser', '') == 'yes':
            email_to.append('%s <%s>' % (access_request['fullname'], access_request['email']))
        if e_template.get('sendtoadmins', '') == 'yes':
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
                email_to.append('%s <%s>' % (profile.title, profile.email))
        for member in e_template.get('selected_list', []):
            email_to.append(member)
        email_data['to'] = email_to
        email_data['subject'] = self.replace_keywords(e_template['subject'], access_request)
        return email_data

    def get_default_msg(self, email, response_type):
        access_request = self.context.access_requests[email]
        default_email = {}
        default_email['email'] = email

        if response_type == 'deny':
            default_email['subject'] = 'Access Request to %s has been denied' % (
                get_setting(self.context, 'title'))
            default_email['to'] = '%s <%s>' % (access_request['fullname'], access_request['email'])
            default_email['from'] = get_setting(self.context, 'admin_email')
            default_email['body'] = u'''<html><body>
        <p>Hello %(name)s,</p>
        <p>Your access request has been denied. Please read the guidelines on
           requesting access to %(system_name)s</p>
        </body></html>''' % {
                'name': access_request['fullname'],
                'system_name': get_setting(self.context, 'title')
            }
            return default_email
        elif response_type == 'approve':
            body_template = get_renderer('templates/admin/email_invite_new.pt').implementation()
            default_email['From'] = '%s <%s>' % (
                get_setting(self.context, 'title'),
                get_setting(self.context, 'admin_email'))
            invitation = self.get_invitation(email)
            default_email['To'] = invitation.email
            default_email['Subject'] = 'Please join %s' % get_setting(self.context, 'title')
            default_email['body'] = body_template(
                system_name=get_setting(self.context, 'title'),
                invitation_url=resource_url(invitation.__parent__, self.request,
                                            invitation.__name__)
                )

    def send_email(self, email_data):
        mailer = getUtility(IMailDelivery)
        message = Message()
        message['Subject'] = email_data['subject']
        message['From'] = email_data['from']
        message['To'] = ",".join(email_data['to'])
        message.set_payload(email_data['body'].encode('UTF-8'), 'UTF-8')
        message.set_type('text/html')
        mailer.send([email_data['email']], message)

    def deny(self, email):
        access_request = self.context.access_requests[email]
        mailer = getUtility(IMailDelivery)
        message = Message()
        message['Subject'] = 'Access Request to %s has been denied' % (
            get_setting(self.context, 'title'))
        message['From'] = get_setting(self.context, 'admin_email')
        body = u'''<html><body>
    <p>Hello %(name)s,</p>
    <p>Your access request has been denied. Please read the guidelines on
       requesting access to %(system_name)s</p>
    </body></html>''' % {
            'name': access_request['fullname'],
            'system_name': get_setting(self.context, 'title')
        }
        message.set_payload(body.encode('UTF-8'), 'UTF-8')
        message.set_type('text/html')
        message['To'] = '%s <%s>' % (access_request['fullname'], access_request['email'])
        mailer.send([access_request['email']], message)

    def delete_request(self, email):
        if email in self.context.access_requests:
            del self.context.access_requests[email]

    def get_invitation(self, email):
        html_body = '''<p>Your access request has been approved<p>'''
        total, docids, resolver = self.search(email=email.lower(),
                                              interfaces=[IInvitation])
        if total:
            # already have invite, re-use
            invitation = resolver(docids[0])
        else:
            # Invite new user to Karl
            invitation = create_content(
                ISiteInvitation,
                email,
                html_body
            )
            while 1:
                name = self.random_id(20)
                if name not in self.invitations:
                    self.invitations[name] = invitation
                    break
        return invitation

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Edit Email Group')

        actions = []
        requestor_email = request.subpath
        requestor_email = requestor_email[0]
        access_request = self.context.access_requests[requestor_email]
        requestor_name = access_request['fullname']

        response_templates = [('', 'None')]
        for e_t in self.context.email_templates:
            response_templates.append((e_t, e_t))
        response_templates.append(('custom', 'Custom'))

        review_choices = [
            ('', 'None'),
            ('approve', 'Approve'),
            ('deny', 'Deny'),
            ('clear', 'Clear'),
            ('follow_up', 'Follow Up')
        ]

        if 'save' in request.params or 'submit' in request.params:
            template_choice = request.params.get('templ_ch')
            rvw_action = request.params.get('rvw_ch')

            # make sure user doesn't already exist
            total, docids, resolver = self.search(email=requestor_email.lower(),
                                                  interfaces=[IProfile])
            if total:
                self.delete_request(requestor_email)
                status_message = "%s already a user on system, deleting" % requestor_email

            if template_choice == 'custom':
                redirect_to = resource_url(context,
                                           request,
                                           'custom_email',
                                           query={'address': requestor_email,
                                                  'action': rvw_action})
                return HTTPFound(location=redirect_to)
            if rvw_action == 'approve':
                if template_choice != '':
                    email_data = self.get_templ_msg(requestor_email, template_choice, 'approve')
                else:
                    email_data = self.get_default_msg(requestor_email, 'approve')
                self.send_email(email_data)
                self.delete_request(requestor_email)
                status_message = "Approved: %s" % requestor_email

            elif rvw_action == 'deny':
                if requestor_email in self.context.access_requests:
                    if template_choice != '':
                        email_data = self.get_templ_msg(requestor_email, template_choice, 'deny')
                    else:
                        email_data = self.get_default_msg(requestor_email, 'deny')
                    self.send_email(email_data)
                    self.delete_request(requestor_email)

                    add_denial(self.context,
                               requestor_email,
                               requestor_name,
                               email_data['subject'],
                               email_data['body'])
                    status_message = "Denied: %s" % requestor_email
            elif rvw_action == 'clear':
                self.delete_request(requestor_email)
                status_message = "Clear access request: %s" % requestor_email
            elif rvw_action == 'follow_up':
                if template_choice != '':
                    email_data = self.get_templ_msg(requestor_email, template_choice, 'follow_up')
                    self.send_email(email_data)
                    status_message = "Follow up sent to %s" % requestor_email
                else:
                    status_message = "Follow up regarding %s skipped because " + \
                        "no template was specified" % requestor_email

            if has_permission(ADMINISTER, context, request):
                redirect_to = resource_url(
                    context, request, 'review_access_requests.html',
                    query=dict(status_message=status_message))
            else:
                redirect_to = resource_url(
                    find_communities(context), request, 'all_communities.html',
                    query=dict(status_message=status_message))

            return HTTPFound(location=redirect_to)

        return dict(
            api=api,
            actions=actions,
            menu=_menu_macro(),
            requestor_email=requestor_email,
            requestor_name=requestor_name,
            review_choices=review_choices,
            response_templates=response_templates,
        )


class ReviewAccessCustom(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def send_email(self, subject, body, addressed_to, from_email):
        message = create_message(self.request, subject, body, from_email)
        if get_config_setting('use_threads_to_send_email', False) in (True, 'true', 'True'):  # noqa
            mailer = ThreadedGeneratorMailDelivery()
            mailer.sendGenerator(
                _send_email, mailer, message, addressed_to)
        else:
            mailer = getUtility(IMailDelivery)
            _send_email(mailer, message, addressed_to)

    def __call__(self):
        context, request = self.context, self.request
        api = AdminTemplateAPI(context, request, 'Admin UI: Custom Email')
        admin_email = get_setting(context, 'admin_email')

        requestor_email = self.request.GET.get('address', '')
        request_action = self.request.GET.get('action', '')
        access_request = self.context.access_requests[requestor_email]
        requestor_name = access_request['fullname']
        print('GET', requestor_email, request_action)

        if 'send_email' in request.params or 'submit' in request.params:
            n = 0
            addressed_to = []
            # parse additional to email addresses
            if request.params['more_to']:
                more_to = request.params['more_to'].split(",")
                for to_email in more_to:
                    emailparts = to_email.split("@")
                    if len(emailparts) != 2:
                        continue
                    # could validate email more here
                    addressed_to.append({
                        'name': emailparts[0],
                        'email': to_email
                    })
                    n += 1
            self.send_email(request.params['subject'],
                            request.params['text'],
                            addressed_to,
                            admin_email)
            if requestor_email in self.context.access_requests:
                del self.context.access_requests[requestor_email]
            add_denial(self.context,
                       requestor_email,
                       requestor_name,
                       request.params['subject'],
                       request.params['text'])
            if has_permission(ADMINISTER, context, request):
                redirect_to = resource_url(context, request, 'review_access_requests.html')
            else:
                redirect_to = resource_url(
                    find_communities(context), request, 'all_communities.html')

            return HTTPFound(location=redirect_to)

        return dict(
            api=api,
            menu=_menu_macro(),
            requestor_email=requestor_email
        )


class ReviewAccessRequestView(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request
    def __call__(self):
        messages = []

        api = AdminTemplateAPI(self.context, self.request)
        api.status_messages = messages

        filtered_results = {}
        hide_repeated_denials = self.context.settings.get('hide_repeated_denials', False)
        if hide_repeated_denials:
            for k, v in self.context.access_requests.iteritems():
                tmp_email = v.get('emai', '')
                # do a lookup to see if this person has been denied previously
                if tmp_email not in self.context.denial_tracker:
                    filtered_results[k] = v
        else:
            filtered_results = self.context.access_requests
        return {
            'api': api,
            'page_title': 'Review Access Requests',
            'format_date': lambda date: date.strftime(TIMEAGO_FORMAT),
            'menu': _menu_macro(),
            'access_requests': reversed(sorted(filtered_results.values(),
                                        key=lambda r: r['date_requested'])),
            'fields': get_access_request_fields(self.context),
        }


class BaseSiteFormController(object):
    page_title = 'Form'

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def form_fields(self):
        return self.schema

    def __call__(self):
        context = self.context
        request = self.request
        api = AdminTemplateAPI(context, request)
        return {'api': api,
                'actions': [],
                'page_title': self.page_title,
                'menu': _menu_macro()
                }


class EditFooterFormController(BaseSiteFormController):
    page_title = 'Edit footer'
    schema = [
        ('footer_html', schemaish.String(
            validator=validator.Required(),
            description="HTML for footer")),
    ]

    def form_defaults(self):
        return {
            'footer_html': self.context.settings['footer_html']
        }

    def form_widgets(self, fields):
        return {
            'footer_html': karlwidgets.RichTextWidget(empty=''),
        }

    def handle_submit(self, converted):
        self.context.settings['footer_html'] = converted['footer_html']
        location = resource_url(self.context, self.request, 'admin.html')
        return HTTPFound(location=location)


class SiteSettingsFormController(BaseSiteFormController):
    page_title = 'Site Settings'

    fields = (
        'title',
        'recaptcha_api_site_key',
        'recaptcha_api_secret_key',
        'reply_by_email_enabled',
        'admin_email',
        'system_list_subdomain',
        'system_email_domain',
        'site_url',
        'max_upload_size',
        'min_pw_length',
        'selectable_groups',
        'date_format',
        'default_home_behavior',
        'site_override_css',
        'safe_html',
        'google_analytics_id',
        'navigation_list',
        )
    labels = {
        'title': 'Site title',
        'min_pw_length': 'Minimum Password Length',
        'default_home_behavior': 'Where user should be directed to by default',
        'reply_by_email_enabled': 'Requires additional configuration',
        'navigation_list':
            'List of links to display on every page. Must be in the format '
            '`Display Name|/url|CSS Class List`. The "Display Name" is a human readable '
            'name, the "/url" is a full, absolute, or relative URL. The "CSS '
            'Class List" is a space separated list of CSS class names that '
            'will be added to each header menu link. All three are '
            'separated by a pipe ("|") character and the "CSS Class List" may '
            'optionally be present.',
    }
    required = ['title', 'admin_email', 'system_list_subdomain', 'system_email_domain',
                'site_url', 'min_pw_length', 'selectable_groups', 'date_format',
                'default_home_behavior']
    ints = ['min_pw_length', 'max_upload_size']
    bools = ['reply_by_email_enabled', 'safe_html']

    schema = []
    for field in fields:
        args = {}
        if field in labels:
            args['description'] = labels[field]
        if field in required:
            args['validator'] = validator.Required()
        FieldClass = schemaish.String
        if field in ints:
            FieldClass = schemaish.Integer
        if field in bools:
            FieldClass = schemaish.Boolean
        schema.append((field, FieldClass(**args)))

    def form_defaults(self):
        data = {}
        for field in self.fields:
            data[field] = self.context.settings.get(
                field, self.context._default_settings.get(field))
        return data

    def form_widgets(self, fields):
        widgets = {}
        for field in self.fields:
            widgets[field] = formish.widgets.Input()
        widgets['default_home_behavior'] = formish.widgets.SelectChoice(
            DEFAULT_HOME_BEHAVIOR_OPTIONS)
        widgets['site_override_css'] = formish.widgets.TextArea()
        widgets['navigation_list'] = formish.widgets.TextArea()
        for bfield in self.bools:
            widgets[bfield] = formish.widgets.Checkbox()
        return widgets

    def handle_submit(self, converted):
        for field in self.fields:
            self.context.settings[field] = converted[field]
        location = resource_url(self.context, self.request, 'admin.html')
        return HTTPFound(location=location)


class AuthenticationFormController(BaseSiteFormController):
    page_title = 'Authentication Settings'
    schema = [
        ('two_factor_enabled', schemaish.Boolean(
            description="Enable 2 factor authentication")),
        ('two_factor_src_phone_number', schemaish.String(
            description="Source phone number for sending SMS auth codes. "
                        "Must include country code")),
        ('two_factor_plivo_auth_id', schemaish.String(
            description="Plivo auth id to allow users to get auth code sent to their phone")),
        ('two_factor_plivo_auth_token', schemaish.String(
            description="Plivo auth token")),
        ('two_factor_auth_code_valid_duration', schemaish.Integer(
            description="How long 2 factor auth codes are valid for"
        )),
        ('failed_login_attempt_window', schemaish.Integer(
            description="Window in seconds to track login attempts"
        )),
        ('max_failed_login_attempts', schemaish.Integer(
            description="Max number of failed login attempts over window"
        )),
    ]

    def form_defaults(self):
        return {
            'two_factor_enabled': self.context.settings.get('two_factor_enabled', False),
            'two_factor_auth_code_valid_duration': self.context.settings.get(
                'two_factor_auth_code_valid_duration', 300),
            'two_factor_src_phone_number': self.context.settings.get(
                'two_factor_src_phone_number', ''),
            'two_factor_plivo_auth_id': self.context.settings.get(
                'two_factor_plivo_auth_id', ''),
            'two_factor_plivo_auth_token': self.context.settings.get(
                'two_factor_plivo_auth_token', ''),
            'failed_login_attempt_window': self.context.settings.get(
                'failed_login_attempt_window', 3600),
            'max_failed_login_attempts': self.context.settings.get(
                'max_failed_login_attempts', 15),
        }

    def form_widgets(self, fields):
        return {
            'two_factor_enabled': formish.widgets.Checkbox(),
            'two_factor_auth_code_valid_duration': formish.widgets.Input(),
            'max_failed_login_attempts': formish.widgets.Input(),
            'failed_login_attempt_window': formish.widgets.Input(),
            'two_factor_plivo_auth_id': formish.widgets.Input(),
            'two_factor_plivo_auth_token': formish.widgets.Input(),
            'two_factor_src_phone_number': formish.widgets.Input(),
        }

    def handle_submit(self, converted):
        self.context.settings['two_factor_enabled'] = converted['two_factor_enabled']
        self.context.settings['two_factor_auth_code_valid_duration'] = converted['two_factor_auth_code_valid_duration']  # noqa
        self.context.settings['max_failed_login_attempts'] = converted['max_failed_login_attempts']  # noqa
        self.context.settings['failed_login_attempt_window'] = converted['failed_login_attempt_window']  # noqa
        self.context.settings['two_factor_plivo_auth_id'] = converted['two_factor_plivo_auth_id']  # noqa
        self.context.settings['two_factor_plivo_auth_token'] = converted['two_factor_plivo_auth_token']  # noqa
        self.context.settings['two_factor_src_phone_number'] = converted['two_factor_src_phone_number']  # noqa
        location = resource_url(self.context, self.request, 'admin.html')
        return HTTPFound(location=location)


class RegistrationFormController(BaseSiteFormController):
    page_title = 'Registration Settings'
    fields = ('allow_request_accesss', 'hide_repeated_denials', 'request_access_fields',
              'request_access_user_message', 'show_terms_and_conditions',
              'terms_and_conditions', 'show_privacy_statement',
              'privacy_statement', 'member_fields')

    schema = [
        ('allow_request_accesss', schemaish.Boolean(
            description="Allow people to request access to site")),
        ('hide_repeated_denials', schemaish.Boolean(
            description="Do not show requests for users that have already been denied")),
        ('request_access_fields', schemaish.Sequence(
            schemaish.String(),
            description="Field access request form should present to user. "
                        "One per line.")),
        ('request_access_user_message', schemaish.String(
            description='Message to send user after access requested')),
        ('show_terms_and_conditions', schemaish.Boolean(
            description="Show terms and conditions")),
        ('terms_and_conditions', schemaish.String()),
        ('show_privacy_statement', schemaish.Boolean(
            description="Show privacy statement")),
        ('privacy_statement', schemaish.String()),
        ('member_fields', schemaish.Sequence(schemaish.String()))
    ]

    def form_defaults(self):
        defaults = {}
        for field in self.fields:
            defaults[field] = get_setting(self.context, field)
        return defaults

    def form_widgets(self, fields):
        return {
            'allow_request_accesss': formish.widgets.Checkbox(),
            'hide_repeated_denials': formish.widgets.Checkbox(),
            'request_access_fields': karlwidgets.SequenceTextAreaWidget(),
            'show_terms_and_conditions': formish.widgets.Checkbox(),
            'terms_and_conditions': karlwidgets.RichTextWidget(empty=''),
            'show_privacy_statement': formish.widgets.Checkbox(),
            'privacy_statement': karlwidgets.RichTextWidget(empty=''),
            'member_fields': formish.widgets.CheckboxMultiChoice(
                [(f, f) for f in Profile.additional_fields]),
            'request_access_user_message': karlwidgets.RichTextWidget(empty='')

        }

    def handle_submit(self, converted):
        # to update
        for field in self.fields:
            self.context.settings[field] = converted[field]
        location = resource_url(self.context, self.request, 'admin.html')
        return HTTPFound(location=location)
