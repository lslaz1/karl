import logging
from time import time
from karl.utils import find_users
from karl.utils import get_setting


log = logging.getLogger(__name__)


class LockoutManager(object):

    def __init__(self, site, login):
        self.site = site
        self.login = login
        self.users = find_users(site)
        try:
            self.login_attempts = site.failed_login_attempts
        except AttributeError:
            log.warn('Upgrade step to install login_attempts storage not run')
            self.login_attempts = None

    def get_attempts_this_window(self):
        if self.login_attempts is None:
            return []

        if self.login not in self.login_attempts:
            return []
        else:
            attempts = self.login_attempts[self.login]

        window = get_setting(self.site, 'failed_login_attempt_window', 3600)

        now = time()
        startperiod = now - window
        period_attempts = []
        for tt in attempts:
            if tt > startperiod and tt <= now:
                period_attempts.append(tt)
        return period_attempts

    def add_attempt(self):
        if self.login_attempts is None:
            return
        attempts = self.get_attempts_this_window()
        attempts.append(time())
        self.login_attempts[self.login] = attempts

    def maxed_number_of_attempts(self):
        attempts = self.get_attempts_this_window()
        max_number = get_setting(self.site, 'max_failed_login_attempts', 15)
        return len(attempts) >= max_number

    def clear(self):
        if self.login_attempts is None:
            return
        if self.login in self.login_attempts:
            del self.login_attempts[self.login]