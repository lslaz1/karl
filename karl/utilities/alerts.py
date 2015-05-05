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

from repoze.postoffice.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import logging
import traceback
from cStringIO import StringIO

import transaction

from zope.component import getMultiAdapter
from zope.component import getUtility
from zope.interface import implements

from pyramid.renderers import get_renderer
from repoze.sendmail.interfaces import IMailDelivery

from karl.models.interfaces import IProfile

from karl.utilities.interfaces import IAlerts
from karl.utilities.interfaces import IAlert
from karl.utils import find_community
from karl.utils import find_profiles
from karl.utils import get_setting
from karl.utils import get_config_setting
from karl.utilities.mailer import ThreadedGeneratorMailDelivery

log = logging.getLogger(__name__)


def _send_alert_queue(mailer, alerts):
    for alert in alerts:
        mailer.send(alert.mto, alert.message)


class Alerts(object):
    implements(IAlerts)

    def emit(self, context, request):
        # Get community in which event occurred and alert members
        community = find_community(context)
        if community is None:
            return  # Will be true for a mailin test trace
        profiles = find_profiles(context)
        all_names = community.member_names | community.moderator_names

        threaded = get_config_setting('use_threads_to_send_email', False) in (True, 'true', 'True')  # noqa
        mailer = getUtility(IMailDelivery)
        if threaded:
            mailer = ThreadedGeneratorMailDelivery()
        queue = []

        reply_enabled = get_setting(context, 'reply_by_email_enabled', True)

        for profile in [profiles[name] for name in all_names]:
            alert = getMultiAdapter((context, profile, request), IAlert)
            preference = profile.get_alerts_preference(community.__name__)
            alert = getMultiAdapter((context, profile, request), IAlert)

            alert.reply_enabled = reply_enabled

            if preference == IProfile.ALERT_IMMEDIATELY:
                if threaded:
                    queue.append(alert)
                else:
                    self._send_immediately(mailer, alert)
            elif preference in (IProfile.ALERT_DAILY_DIGEST,
                                IProfile.ALERT_WEEKLY_DIGEST,
                                IProfile.ALERT_BIWEEKLY_DIGEST):
                self._queue_digest(alert, profile, community.__name__)

        if queue:
            mailer.sendGenerator(_send_alert_queue, mailer, queue)

    def _send_immediately(self, mailer, alert):
        mailer.send(alert.mto, alert.message)

    def _queue_digest(self, alert, profile, community):
        alert.digest = True
        message = alert.message

        # If message has atachments, body will be list of message parts.
        # First part contains body text, the rest contain attachments.
        if message.is_multipart():
            parts = message.get_payload()
            body = parts[0].get_payload(decode=True)
            attachments = parts[1:]
        else:
            body = message.get_payload(decode=True)
            attachments = []

        profile._pending_alerts.append(
            {"from": message["From"],
             "to": message["To"],
             "subject": message["Subject"],
             "body": body,
             "attachments": attachments,
             "community": community,
             })

    def send_digests(self, context, period='daily'):
        PERIODS = {'daily': [IProfile.ALERT_DAILY_DIGEST],
                   'weekly': [IProfile.ALERT_DAILY_DIGEST,
                              IProfile.ALERT_WEEKLY_DIGEST],
                   'biweekly': [IProfile.ALERT_DAILY_DIGEST,
                                IProfile.ALERT_WEEKLY_DIGEST,
                                IProfile.ALERT_BIWEEKLY_DIGEST],
                   }
        periods = PERIODS[period]
        mailer = getUtility(IMailDelivery)

        system_name = get_setting(context, "title", "KARL")
        sent_from = get_setting(context, "admin_email")
        from_addr = "%s <%s>" % (system_name, sent_from)
        subject = "[%s] Your alerts digest" % system_name

        template = get_renderer("email_digest.pt").implementation()
        for profile in find_profiles(context).values():
            if not list(profile._pending_alerts):
                continue

            # Perform each in its own transaction, so a problem with one
            # user's email doesn't block all others
            transaction.manager.begin()
            alerts = profile._pending_alerts.consume()
            try:
                pending = []
                skipped = []
                for alert in alerts:
                    community = alert.get('community')
                    if community is not None:
                        pref = profile.get_alerts_preference(community)
                        if pref in periods:
                            pending.append(alert)
                        else:
                            skipped.append(alert)
                    else:  # XXX belt-and-suspenders:  send it now
                        pending.append(alert)

                if len(pending) > 0:

                    attachments = []
                    for alert in pending:
                        attachments += alert['attachments']

                    msg = MIMEMultipart() if attachments else Message()
                    msg["From"] = from_addr
                    msg["To"] = "%s <%s>" % (profile.title, profile.email)
                    msg["Subject"] = subject

                    body_text = template.render(
                        system_name=system_name,
                        alerts=pending,
                    )

                    if isinstance(body_text, unicode):
                        body_text = body_text.encode("UTF-8")

                    if attachments:
                        body = MIMEText(body_text, 'html', 'utf-8')
                        msg.attach(body)
                    else:
                        msg.set_payload(body_text, "UTF-8")
                        msg.set_type("text/html")

                    for attachment in attachments:
                        msg.attach(attachment)

                    mailer.send([profile.email], msg)

                for alert in skipped:
                    profile._pending_alerts.append(alert)

                transaction.manager.commit()

            except Exception:
                # Log error and continue
                log.error("Error sending digest to %s <%s>" %
                          (profile.title, profile.email))

                b = StringIO()
                traceback.print_exc(file=b)
                log.error(b.getvalue())
                b.close()

                transaction.manager.abort()
