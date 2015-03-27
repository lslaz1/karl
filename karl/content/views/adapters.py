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
from __future__ import with_statement

import math

from email import Encoders
from repoze.postoffice.message import Message
from repoze.postoffice.message import MIMEMultipart
from email.mime.multipart import MIMEBase
from email.mime.text import MIMEText

from lxml import etree
from lxml.html import document_fromstring

from zope.component import getUtility
from zope.interface import implements

from pyramid.renderers import get_renderer
from pyramid.traversal import find_interface
from pyramid.url import resource_url

from karl.content.interfaces import IBlogEntry
from karl.content.interfaces import ICalendarEvent
from karl.models.interfaces import IComment
from karl.models.interfaces import ICommunity
from karl.content.interfaces import IForumTopic
from karl.content.interfaces import IReferencesFolder
from karl.content.interfaces import IReferenceManual
from karl.content.interfaces import IReferenceSection
from karl.content.interfaces import IWikiPage
from karl.content.views.interfaces import INetworkEventsMarker
from karl.content.views.interfaces import INetworkNewsMarker
from karl.content.interfaces import ICommunityFile
from karl.content.views.interfaces import IFileInfo
from karl.content.views.interfaces import IBylineInfo
from karl.content.views.interfaces import IShowSendalert
from karl.utilities.interfaces import IAlert
from karl.utilities.interfaces import IKarlDates
from karl.utilities.interfaces import IMimeInfo
from karl.views.interfaces import IFolderAddables
from karl.views.interfaces import ILayoutProvider
from karl.models.interfaces import ICommentsFolder

from karl.utils import docid_to_hex
from karl.utils import get_setting
from karl.utils import find_community
from karl.utils import find_profiles

# Imports used for the purpose of package_path
from karl.views import site
site = site      # shut up pylint

MAX_ATTACHMENT_SIZE = (1 << 20) * 5  # 5 megabytes


class FileInfo(object):
    """ Adapter for showing file entry data in views """
    implements(IFileInfo)
    _url = None
    _modified = None
    _modified_by_title = None
    _modified_by_url = None
    _mimeinfo = None
    _size = None

    def __init__(self, context, request):
        self.context = context
        self.request = request

    @property
    def name(self):
        return self.context.__name__

    @property
    def title(self):
        return self.context.title

    @property
    def modified(self):
        if self._modified is None:
            self._modified = self.context.modified.strftime("%m/%d/%Y")
        return self._modified

    def _find_profile(self, profile_name):
        if profile_name is None:
            return None
        profiles = find_profiles(self.context)
        return profiles.get(profile_name, None)

    @property
    def modified_by_title(self):
        if self._modified_by_title is None:
            profile_name = self.context.modified_by or self.context.creator
            profile = self._find_profile(profile_name)
            self._modified_by_title = profile and profile.title
        return self._modified_by_title

    @property
    def modified_by_url(self):
        if self._modified_by_url is None:
            profile_name = self.context.modified_by or self.context.creator
            profile = self._find_profile(profile_name)
            self._modified_by_url = profile and resource_url(profile, self.request)
        return self._modified_by_url

    @property
    def url(self):
        if self._url is None:
            self._url = resource_url(self.context, self.request)
        return self._url

    @property
    def mimeinfo(self):
        if self._mimeinfo is None:
            mimetype = getattr(self.context, 'mimetype', None)
            if mimetype is None:
                self._mimeinfo = {'small_icon_name': 'files_folder_small.png',
                                  'title': 'Folder'}
            else:
                mimeutil = getUtility(IMimeInfo)
                self._mimeinfo = mimeutil(mimetype)
            self._mimeinfo['small_icon_url'] = self.request.static_url(
                'karl.views:static/images/%s' %
                self._mimeinfo['small_icon_name'])
        return self._mimeinfo

    @property
    def size(self):
        if self._size is None:
            powers = ["bytes", "KB", "MB", "GB", "TB"]  # Future proof ;)
            size = self.context.size
            if size > 0:
                power = int(math.log(size, 1000))
                assert power < len(powers), "File is larger than 999 TB"
            else:
                power = 0

            if power == 0:
                self._size = "%d %s" % (size, powers[0])

            else:
                size = float(size) / (1000 ** power)
                self._size = "%0.1f %s" % (size, powers[power])

        return self._size


class CalendarEventFileInfo(FileInfo):
    @property
    def mimeinfo(self):
        return {
            "small_icon_name": "files_event_small.png",
            "title": "Event"
        }


class PageFileInfo(FileInfo):
    @property
    def mimeinfo(self):
        return {
            "small_icon_name": "files_page_small.png",
            "title": "Page"
        }


class ReferenceManualFileInfo(FileInfo):
    @property
    def mimeinfo(self):
        return {
            "small_icon_name": "files_manual_small.png",
            "title": "Reference Manual"
        }


class ReferenceSectionFileInfo(FileInfo):
    @property
    def mimeinfo(self):
        return {
            "small_icon_name": "files_manual_small.png",
            "title": "Reference Section"
        }


class BylineInfo(object):
    """ Adapter to grab resource info for the byline in ZPT """
    implements(IBylineInfo)
    _author_url = None
    _author_name = None
    _posted_date = None
    _posted_date_compact = None

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.profile = find_profiles(context).get(context.creator)

    @property
    def author_url(self):
        if self._author_url is None:
            self._author_url = resource_url(self.profile, self.request)
        return self._author_url

    @property
    def author_name(self):
        if self._author_name is None:
            if self.profile:
                self._author_name = self.profile.title
            else:
                self._author_name = None
        return self._author_name

    @property
    def posted_date(self):
        if self._posted_date is None:
            kd = getUtility(IKarlDates)
            self._posted_date = kd(self.context.created, 'longform')
        return self._posted_date

    @property
    def posted_date_compact(self):
        if self._posted_date_compact is None:
            kd = getUtility(IKarlDates)
            self._posted_date_compact = kd(self.context.created, 'compact')
        return self._posted_date_compact


class Alert(object):
    """Base adapter class for generating emails from alerts.
    """
    implements(IAlert)

    mfrom = None
    message = None
    digest = False
    _attachments_folder = None

    def __init__(self, context, profile, request):
        self.context = context
        self.profile = profile
        self.request = request

        self.profiles = profiles = find_profiles(context)
        self.creator = profiles[context.creator]

    @property
    def mto(self):
        return [self.profile.email]

    @property
    def attachments(self):
        folder = self._attachments_folder
        if folder is None:
            return [], [], {}

        profile = self.profile
        request = self.request
        attachments = []
        attachment_links = []
        attachment_hrefs = {}
        for name, model in folder.items():
            if profile.alert_attachments == 'link':
                attachment_links.append(name)
                attachment_hrefs[name] = resource_url(model, request)

            elif profile.alert_attachments == 'attach':
                with model.blobfile.open() as f:
                    f.seek(0, 2)
                    size = f.tell()
                    if size > MAX_ATTACHMENT_SIZE:
                        attachment_links.append(name)
                        attachment_hrefs[name] = resource_url(model, request)

                    else:
                        f.seek(0, 0)
                        data = f.read()
                        type, subtype = model.mimetype.split('/', 1)
                        attachment = MIMEBase(type, subtype)
                        attachment.set_payload(data)
                        Encoders.encode_base64(attachment)
                        attachment.add_header(
                            'Content-Disposition',
                            'attachment; filename="%s"' % model.filename)
                        attachments.append(attachment)

        return attachments, attachment_links, attachment_hrefs


class BlogAlert(Alert):
    """Adapter for generating an email from a blog entry alert.
    """
    _mfrom = None
    _message = None
    _template = None
    _subject = None

    def __init__(self, context, profile, request):
        super(BlogAlert, self).__init__(context, profile, request)
        self._community = find_community(context)
        blogentry = find_interface(context, IBlogEntry)
        if blogentry is None:
            # Comments can also be made against forum topics
            blogentry = find_interface(context, IForumTopic)
        self._blogentry = blogentry

    @property
    def mfrom(self):
        if self._mfrom is not None:
            return self._mfrom

        system_email_domain = get_setting(self.context, "system_email_domain")
        mfrom = "%s@%s" % (self._community.__name__, system_email_domain)
        self._mfrom = mfrom
        return mfrom

    @property
    def message(self):
        if self._message is not None:
            return self._message

        community = self._community
        request = self.request
        profile = self.profile
        blogentry = self._blogentry

        community_href = resource_url(community, request)
        blogentry_href = resource_url(blogentry, request)
        manage_preferences_href = resource_url(profile, request) + '/manage_communities.html'  # noqa
        system_name = get_setting(self.context, "title", "KARL")
        system_email_domain = get_setting(self.context, "system_email_domain")

        reply_to = '"%s" <%s+blog-%s@%s>' % (community.title,
                                             community.__name__,
                                             docid_to_hex(blogentry.docid),
                                             system_email_domain)

        attachments, attachment_links, attachment_hrefs = self.attachments

        body_template = get_renderer(self._template).implementation()
        from_name = "%s | %s" % (self.creator.title, system_name)
        msg = MIMEMultipart() if attachments else Message()
        msg["From"] = '"%s" <%s>' % (from_name, self.mfrom)
        msg["To"] = '"%s" <%s>' % (profile.title, profile.email)
        msg["Reply-to"] = reply_to
        msg["Subject"] = self._subject
        msg["Precedence"] = 'bulk'
        body_text = body_template(
            context=self.context,
            community=community,
            community_href=community_href,
            blogentry=blogentry,
            blogentry_href=blogentry_href,
            attachments=attachment_links,
            attachment_hrefs=attachment_hrefs,
            manage_preferences_href=manage_preferences_href,
            profile=profile,
            profiles=self.profiles,
            creator=self.creator,
            digest=self.digest,
            alert=self,
            history=self._history,
        )

        if self.digest:
            # Only interested in body for digest
            html = document_fromstring(body_text)
            body_element = html.cssselect('body')[0]
            span = etree.Element("span", nsmap=body_element.nsmap)
            span[:] = body_element[:]  # Copy all body elements to an empty span
            body_text = etree.tostring(span, pretty_print=True)

        if isinstance(body_text, unicode):
            body_text = body_text.encode('utf-8')

        if attachments:
            body = MIMEText(body_text, 'html', 'utf-8')
            msg.attach(body)
            for attachment in attachments:
                msg.attach(attachment)
        else:
            msg.set_payload(body_text, 'utf-8')
            msg.set_type("text/html")

        self._message = msg

        return self._message

    @property
    def _attachments_folder(self):
        return self._blogentry['attachments']

    @property
    def _history(self):
        """
        Return a tuple, (messages, n), where messages is a list of at most
        three preceding messages considered relevant to the current message. n
        is the total number of messages in the 'thread' for some definition of
        'thread'.
        """
        return ([], 0)


class BlogEntryAlert(BlogAlert):
    _template = "templates/email_blog_entry_alert.pt"

    def __init__(self, context, profile, request):
        super(BlogEntryAlert, self).__init__(context, profile, request)
        assert IBlogEntry.providedBy(context)

    @property
    def _subject(self):
        return "[%s] %s" % (self._community.title, self._blogentry.title)


class BaseCommentAlert(object):

    @property
    def comment_folder(self):
        return find_interface(self.context, ICommentsFolder)

    @property
    def parent(self):
        return self.comment_folder.__parent__

    @property
    def _history(self):
        """ See abstract base class, BlogAlert, above."""
        if self.digest:
            return ([], 0)

        comment_folder = find_interface(self.context, ICommentsFolder)
        parent = comment_folder.__parent__
        comments = list(comment_folder.values())
        comments = [comment for comment in comments
                    if comment is not self.context]
        comments.sort(key=lambda x: x.created)

        messages = [parent] + comments
        n = len(comments) + 1
        return messages, n


class CommentBlogEntryAlert(BaseCommentAlert, BlogAlert):
    _template = "templates/email_blog_comment_alert.pt"

    def __init__(self, context, profile, request):
        BlogAlert.__init__(self, context, profile, request)
        assert IComment.providedBy(context)

    @property
    def _subject(self):
        return "[%s] Re: %s" % (self._community.title, self._blogentry.title)

    @property
    def _attachments_folder(self):
        return self.context


class CommentAlert(Alert):

    def __init__(self, context, profile, request):
        super(CommentAlert, self).__init__(context, profile, request)
        assert IComment.providedBy(context)
        self.alert = None
        if find_interface(self.context, IBlogEntry) or find_interface(context, IForumTopic):  # noqa
            # it is a blog alert
            self.alert = CommentBlogEntryAlert(self.context, self.profile, self.request)
        else:
            if find_interface(self.context, ICommunityFile):
                self.alert = CommunityFileCommentAlert(self.context, self.profile,
                                                       self.request)

    @property
    def message(self):
        if self.alert:
            return self.alert.message


class NonBlogAlert(Alert):
    # XXX Are BlogAlert and NonBlogAlert close enough that they could merged
    #     into Alert?
    _mfrom = None
    _message = None
    _template = None
    _subject = None
    _template = None
    _interface = None
    _content_type_name = None

    def __init__(self, context, profile, request):
        Alert.__init__(self, context, profile, request)
        self._community = find_community(context)
        self._model = find_interface(context, self._interface)
        assert self._interface.providedBy(context)

    @property
    def _subject(self):
        return "[%s] %s" % (self._community.title, self.context.title)

    @property
    def mfrom(self):
        if self._mfrom is not None:
            return self._mfrom

        system_email_domain = get_setting(self.context, "system_email_domain")
        mfrom = "%s@%s" % ('alerts', system_email_domain)
        self._mfrom = mfrom
        return mfrom

    @property
    def message(self):
        if self._message is not None:
            return self._message

        community = self._community
        request = self.request
        profile = self.profile
        model = self._model

        community_href = resource_url(community, request)
        model_href = resource_url(model, request)
        manage_preferences_href = resource_url(profile, request) + '/manage_communities.html'  # noqa
        system_name = get_setting(self.context, "title", "KARL")

        attachments, attachment_links, attachment_hrefs = self.attachments

        body_template = get_renderer(self._template).implementation()
        from_name = "%s | %s" % (self.creator.title, system_name)
        msg = MIMEMultipart() if attachments else Message()
        msg["From"] = '"%s" <%s>' % (from_name, self.mfrom)
        msg["To"] = '"%s" <%s>' % (community.title, profile.email)
        msg["Subject"] = self._subject
        msg["Precedence"] = 'bulk'
        body_text = body_template(
            context=self.context,
            community=community,
            community_href=community_href,
            model=model,
            model_href=model_href,
            manage_preferences_href=manage_preferences_href,
            attachments=attachment_links,
            attachment_hrefs=attachment_hrefs,
            profile=profile,
            profiles=self.profiles,
            creator=self.creator,
            content_type=self._content_type_name,
            digest=self.digest,
            alert=self,
            resource_url=resource_url,
            request=request
        )

        if self.digest:
            # Only interested in body for digest
            html = document_fromstring(body_text)
            body_element = html.cssselect('body')[0]
            span = etree.Element("span", nsmap=body_element.nsmap)
            span[:] = body_element[:]  # Copy all body elements to an empty span
            body_text = etree.tostring(span, pretty_print=True)

        if isinstance(body_text, unicode):
            body_text = body_text.encode('utf-8')

        if attachments:
            body = MIMEText(body_text, 'html', 'utf-8')
            msg.attach(body)
            for attachment in attachments:
                msg.attach(attachment)
        else:
            msg.set_payload(body_text, 'utf-8')
            msg.set_type("text/html")

        self._message = msg
        return msg


class WikiPageAlert(NonBlogAlert):
    _template = "templates/email_wikipage_alert.pt"
    _interface = IWikiPage
    _content_type_name = 'Wiki Page'


class CommunityFileAlert(NonBlogAlert):
    _template = "templates/email_community_file_alert.pt"
    _interface = ICommunityFile
    _content_type_name = 'File'


class CommunityFileCommentAlert(BaseCommentAlert, CommunityFileAlert):
    _template = "templates/email_community_file_comment_alert.pt"
    _interface = IComment

    @property
    def _subject(self):
        return "[%s] Re: %s" % (self._community.title, self.parent.title)


class CalendarEventAlert(NonBlogAlert):
    _template = "templates/email_calendar_event_alert.pt"
    _interface = ICalendarEvent
    _content_type_name = "Event"

    @property
    def startDate(self):
        model = self._model
        if not model.startDate:
            return None
        karldates = getUtility(IKarlDates)
        return karldates(model.startDate, 'longform')

    @property
    def endDate(self):
        model = self._model
        if not model.endDate:
            return None
        karldates = getUtility(IKarlDates)
        return karldates(model.endDate, 'longform')

    @property
    def attendees(self):
        model = self._model
        if not model.attendees:
            return None
        return '; '.join(model.attendees)

    @property
    def _attachments_folder(self):
        return self.context.get('attachments')


class DefaultFolderAddables(object):
    implements(IFolderAddables)

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        """ Based on markers, override what can be added to a folder """
        url = self.request.resource_url
        context = self.context

        # This is the default for all, meaning community, folders
        _addlist = [
            ('Add Folder', url(context, 'add_folder.html')),
            ('Add File', url(context, 'add_file.html')),
            ]

        # Override all addables in certain markers
        if IReferencesFolder.providedBy(self.context):
            _addlist = [('Add Reference Manual',
                         url(context, 'add_referencemanual.html'))]
        elif IReferenceManual.providedBy(self.context):
            _addlist = [
                ('Add Section', url(context, 'add_referencesection.html')),
                ('Add File', url(context, 'add_file.html')),
                ('Add Page', url(context, 'add_page.html')),
                ]
        elif IReferenceSection.providedBy(self.context):
            _addlist = [
                ('Add Section', url(context, 'add_referencesection.html')),
                ('Add File', url(context, 'add_file.html')),
                ('Add Page', url(context, 'add_page.html')),
                ]
        elif INetworkEventsMarker.providedBy(self.context):
            _addlist = [
                ('Add Event', url(context, 'add_calendarevent.html')),
                ]
        elif INetworkNewsMarker.providedBy(self.context):
            _addlist = [
                ('Add News Item', url(context, 'add_newsitem.html')),
                ]
        return _addlist


class DefaultLayoutProvider(object):
    """ Site policy on which o-wrap to choose from for a context"""
    implements(ILayoutProvider)

    def __init__(self, context, request):
        self.context = context
        self.request = request

    @property
    def community_layout(self):
        return get_renderer(
            'karl.views:templates/community_layout.pt').implementation()

    @property
    def generic_layout(self):
        return get_renderer(
            'karl.views:templates/generic_layout.pt').implementation()

    def __call__(self, default=None):
        # The layouts are by identifier, e.g. layout='community'

        # A series of tests, in order of precedence.
        layout = self.generic_layout
        if default is not None:
            layout = getattr(self, default + '_layout')
        elif not find_interface(self.context, ICommunity):
            layout = self.generic_layout

        return layout


class DefaultShowSendalert(object):
    """ Default policies for showing the alert checkbox """
    implements(IShowSendalert)

    def __init__(self, context, request):
        self.context = context
        self.request = request

    @property
    def show_sendalert(self):
        """ Return boolean on whether to suppress this field """

        return True
