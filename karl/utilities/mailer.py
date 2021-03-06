from __future__ import with_statement

import os
import sys
import time
import random
import socket

from email.message import Message

from zope.interface import implements
from repoze.sendmail.delivery import QueuedMailDelivery
from repoze.sendmail.interfaces import IMailDelivery

from karl.utils import get_config_settings

from transaction.interfaces import IDataManager
import transaction

from email.utils import formatdate
from email.header import Header
from repoze.sendmail.maildir import Maildir
import threading


# ripped from: https://github.com/python/cpython/blob/master/Lib/email/utils.py#L186
# the custom domain was added in python 3.2+ but not back-ported
# This is here because email relayed through a system, making the default FQDN
# that gets added to the msgid incorrect, causing messages to be identified more
# readily as possible spam.
def make_msgid(idstring=None, domain=None):
    """Returns a string suitable for RFC 2822 compliant Message-ID, e.g:
    <142480216486.20800.16526388040877946887@nightshade.la.mastaler.com>
    Optional idstring if given is a string used to strengthen the
    uniqueness of the message id.  Optional domain if given provides the
    portion of the message id after the '@'.  It defaults to the locally
    defined hostname.
    """
    timeval = int(time.time()*100)
    pid = os.getpid()
    randint = random.getrandbits(64)
    if idstring is None:
        idstring = ''
    else:
        idstring = '.' + idstring
    if domain is None:
        domain = socket.getfqdn()
    msgid = '<%d.%d.%d%s@%s>' % (timeval, pid, randint, idstring, domain)
    return msgid


def boolean(s):
    s = s.lower()
    return s.startswith('y') or s.startswith('1') or s.startswith('t')


def mail_delivery_factory(os=os):  # accepts 'os' for unit test purposes
    """Factory method for creating an instance of repoze.sendmail.IDelivery
    for use by this application.
    """
    settings = get_config_settings()

    # If settings utility not present, we are probably testing and should
    # suppress sending mail.  Can also be set explicitly in environment
    # variable
    suppress_mail = boolean(os.environ.get('SUPPRESS_MAIL', ''))

    if not settings or suppress_mail:
        return FakeMailDelivery()

    md = KarlMailDelivery(settings)
    if settings.get("mail_white_list", None):
        md = WhiteListMailDelivery(md)
    return md


class KarlMailDelivery(QueuedMailDelivery):
    """
    Uses queued mail delivery from repoze.sendmail, but provides the envelope
    from address from Karl configuration.
    """

    def __init__(self, settings):
        self.mfrom = settings.get('envelope_from_addr', None)
        self.bounce_from = settings.get(
            'postoffice.bounce_from_email', self.mfrom)
        queue_path = settings.get("mail_queue_path", None)
        if queue_path is None:
            # Default to var/mail_queue
            # we assume that the console script lives in the 'bin' dir of a
            # sandbox or buildout, and that the mail_queue directory lives in
            # the 'var' directory of the sandbox or buildout
            exe = sys.executable
            sandbox = os.path.dirname(os.path.dirname(os.path.abspath(exe)))
            queue_path = os.path.join(
                os.path.join(sandbox, "var"), "mail_queue"
            )
            queue_path = os.path.abspath(os.path.normpath(
                os.path.expanduser(queue_path)))

        super(KarlMailDelivery, self).__init__(queue_path)

    def send(self, mto, msg):
        assert isinstance(msg, Message), \
               'Message must be instance of email.message.Message'
        try:
            from repoze.sendmail import encoding
            encoding.cleanup_message(msg)
        except ImportError:
            pass
        messageid = msg['Message-Id']
        if messageid is None:
            settings = get_config_settings()
            msgid_domain = settings.get('msgid_domain', None)
            messageid = msg['Message-Id'] = make_msgid(domain=msgid_domain)
        if msg['Date'] is None:
            msg['Date'] = formatdate()
        transaction.get().join(
            self.createDataManager(self.mfrom, mto, msg))
        return messageid

    def bounce(self, mto, msg):
        self.send(self.bounce_from, mto, msg)


class FakeMailDelivery:
    implements(IMailDelivery)

    def __init__(self, quiet=True):
        self.quiet = quiet

    def send(self, mto, msg):
        if not self.quiet:  # pragma NO COVERAGE
            print 'To:', mto
            print 'Message:', msg

    bounce = send


class WhiteListMailDelivery(object):
    """Decorates an IMailDelivery with a recipient whitelist"""
    implements(IMailDelivery)

    def __init__(self, md):
        self.md = md
        settings = get_config_settings()
        white_list_fn = settings.get("mail_white_list", None)
        if white_list_fn:
            with open(white_list_fn) as f:
                self.white_list = set(
                    self._normalize(line) for line in f.readlines())
        else:
            self.white_list = None

    def _get_queuePath(self):
        return self.md.queuePath
    def _set_queuePath(self, value):
        self.md.queuePath = value
    queuePath = property(_get_queuePath, _set_queuePath)

    def send(self, toaddrs, message):
        self._send(toaddrs, message, self.md.send)

    def bounce(self, toaddrs, message):
        self._send(toaddrs, message, self.md.bounce)

    def _send(self, toaddrs, message, send):
        if self.white_list is not None:
            toaddrs = [addr for addr in toaddrs
                       if self._normalize(addr) in self.white_list]
        if toaddrs:
            send(toaddrs, message)

    @staticmethod
    def _normalize(addr):
        if '<' in addr:
            addr = addr[addr.index('<') + 1:addr.rindex('>')]
        return unicode(addr.strip()).lower()


class ThreadedGeneratorMailDataManager(object):
    implements(IDataManager)

    def __init__(self, mailer, callable, args=()):
        self.callable = callable
        self.mailer = mailer
        self.args = args
        self.transaction_manager = transaction.manager

    def commit(self, transaction):
        pass

    def abort(self, transaction):
        # just do nothing here
        pass

    def sortKey(self):
        return id(self)

    # No subtransaction support.
    def abort_sub(self, transaction):
        pass

    commit_sub = abort_sub

    def beforeCompletion(self, transaction):
        pass

    afterCompletion = beforeCompletion

    def tpc_begin(self, transaction, subtransaction=False):
        assert not subtransaction

    def tpc_vote(self, transaction):
        pass

    def tpc_finish(self, transaction):
        thread = threading.Thread(target=self.callable, args=self.args)
        thread.start()

    tpc_abort = abort


class ThreadedGeneratorMailDelivery(KarlMailDelivery):
    """
    High performance mail delivery class.

    The purpose of this is being able to use a generator
    in a different for all messages you want to send that won't be
    generated until the transaction has finished.
    """

    def __init__(self, settings=None):
        if settings is None:
            settings = get_config_settings()
            self.msgid_domain = settings.get('msgid_domain', None)
        super(ThreadedGeneratorMailDelivery, self).__init__(settings)

    def send(self, mto, message):
        """
        keep in mind...
        This is only called inside another thread, after
        transaction has completed
        """
        try:
            from repoze.sendmail import encoding
            encoding.cleanup_message(message)
        except ImportError:
            pass
        messageid = message['Message-Id']
        if messageid is None:
            msgid_domain = self.msgid_domain
            messageid = message['Message-Id'] = make_msgid(domain=msgid_domain)
        if message['Date'] is None:
            message['Date'] = formatdate()

        message['X-Actually-From'] = Header(self.mfrom, 'utf-8')
        message['X-Actually-To'] = Header(','.join(mto), 'utf-8')
        maildir = Maildir(self.queuePath, True)
        tx_message = maildir.add(message)
        tx_message.commit()
        return messageid

    def sendGenerator(self, generator, *args):
        transaction.get().join(
            ThreadedGeneratorMailDataManager(self, generator, args))
