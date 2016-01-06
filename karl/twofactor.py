import html2text
import json
from karl.utils import strings_differ
from karl.utils import find_profiles
from datetime import timedelta
from datetime import datetime
from karl.utils import make_random_code
from karl.utils import get_setting
from repoze.postoffice.message import MIMEMultipart
from email.mime.text import MIMEText
from repoze.sendmail.interfaces import IMailDelivery
from zope.component import getUtility
import requests
import string


class TwoFactor(object):

    def __init__(self, context, request):
        self.context = context
        self.request = request

    @property
    def enabled(self):
        return get_setting(self.context, 'two_factor_enabled', False)

    @property
    def phone_factor_enabled(self):
        return bool(
            get_setting(self.context, 'two_factor_plivo_auth_id', False) and
            get_setting(self.context, 'two_factor_plivo_auth_token', False) and
            get_setting(self.context, 'two_factor_src_phone_number', False))

    def validate(self, userid, code):
        profiles = find_profiles(self.context)
        profile = profiles.get(userid)
        window = get_setting(self.context, 'two_factor_auth_code_valid_duration', 300)
        now = datetime.utcnow()
        return (strings_differ(code, profile.current_auth_code) or
                now > (profile.current_auth_code_time_stamp + timedelta(seconds=window)))

    def send_mail_code(self, profile):
        mailer = getUtility(IMailDelivery)
        message = MIMEMultipart('alternative')
        message['From'] = get_setting(self.context, 'admin_email')
        message['To'] = '%s <%s>' % (profile.title, profile.email)
        message['Subject'] = '%s Authorization Request' % self.context.title
        bodyhtml = u'''<html><body>
    <p>An authorization code has been requested for the site %s.</p>
    <p>Authorization Code: <b>%s</b></p>
    </body></html>''' % (
            self.request.application_url,
            profile.current_auth_code
        )
        bodyplain = html2text.html2text(bodyhtml)
        htmlpart = MIMEText(bodyhtml.encode('UTF-8'), 'html', 'UTF-8')
        plainpart = MIMEText(bodyplain.encode('UTF-8'), 'plain', 'UTF-8')
        message.attach(plainpart)
        message.attach(htmlpart)
        mailer.send([profile.email], message)

    def send_text_code(self, profile):
        msg = "%s authorization code: %s" % (
            get_setting(self.context, 'title'),
            profile.current_auth_code)
        self.send_text_to_number(profile.two_factor_phone, msg)

    def send_code(self, profile):
        # get and set current auth code
        profile.current_auth_code = make_random_code(8)
        profile.current_auth_code_time_stamp = datetime.utcnow()

        if self.phone_factor_enabled and profile.two_factor_verified:
            self.send_text_code(profile)
            return 'Authorization code has been sent to the phone number ending with %s.' % (
                profile.two_factor_phone[-4:])
        else:
            self.send_mail_code(profile)
            return 'Authorization code has been sent. Check your email.'

    @property
    def src_number(self):
        src_number = get_setting(self.context, 'two_factor_src_phone_number')
        return ''.join(n for n in src_number if n in string.digits)

    def send_text_to_number(self, number, text):
        number = ''.join(n for n in number if n in string.digits)
        auth_id = get_setting(self.context, 'two_factor_plivo_auth_id', '')
        auth_token = get_setting(self.context, 'two_factor_plivo_auth_token', '')
        params = {
            'src': self.src_number,
            'dst': '1' + number,
            'text': text
        }
        resp = requests.post(
            'https://api.plivo.com/v1/Account/%s/Message/' % auth_id,
            data=json.dumps(params),
            headers={
                'Content-Type': 'application/json'
            },
            auth=(auth_id, auth_token))
        return resp.status_code in (202, 200)
