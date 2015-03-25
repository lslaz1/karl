# ripped out of repoze.whoplugins.zodb since that package doesn't look maintained
# and there is no repository information
from persistent import Persistent
from zope.interface import implements
from hashlib import sha1
import binascii
from BTrees.OOBTree import OOBTree
from karl.models.interfaces import IUsers
from karl.utils import get_random_string
from karl.utils import strings_same
try:
    from hashlib import pbkdf2_hmac
except ImportError:
    import passlib.utils.pbkdf2
    def pbkdf2_hmac(_type, password, salt, rounds):
        return passlib.utils.pbkdf2.pbkdf2(password, salt, rounds, None, 'hmac-' + _type)


def pbkdf2(password, salt):
    if isinstance(password, unicode):
        try:
            password = password.encode('utf8')
        except:
            pass
    return 'pbkdf2:' + binascii.hexlify(pbkdf2_hmac('sha512', password, salt, 64))


def get_sha_password(password):
    if isinstance(password, unicode):
        password = password.encode('UTF-8')
    return 'SHA1:' + sha1(password).hexdigest()


class Users(Persistent):
    implements(IUsers)
    data = None

    def __init__(self):
        self.data = OOBTree()
        self.byid = self.data  # b/c
        self.logins = OOBTree()
        self.groups = OOBTree()

    def _convert(self, s):
        if isinstance(s, basestring):
            if not isinstance(s, unicode):
                s = unicode(s, 'utf-8')
        return s

    def _upgrade(self):
        # older revisions of this class used 2 btrees: "bylogin" and
        # "byid", instead of a "data" btree, a "groups" btree, and a
        # "logins" btree; this method upgrades the persistent
        # state of old instances
        if self.data is None:
            self.data = self.byid
            self.logins = OOBTree()
            self.groups = OOBTree()
            for login, info in self.bylogin.items():
                login = self._convert(login)
                userid = self._convert(info['id'])
                self.logins[login] = userid
                groups = info['groups']
                for group in groups:
                    group = self._convert(group)
                    groupset = self.groups.setdefault(group, set())
                    groupset.add(userid)
                    self.groups[group] = groupset
            del self.bylogin

    def get_by_login(self, login):
        # b/c
        return self.get(login=login)

    def get_by_id(self, userid):
        # b/c
        return self.get(userid=userid)

    def get(self, userid=None, login=None):
        self._upgrade()
        if userid is not None and login is not None:
            raise ValueError('Only one of userid or login may be supplied')

        if userid is not None:
            userid = self._convert(userid)
            return self.data.get(userid)

        if login is not None:
            login = self._convert(login)
            userid = self.logins.get(login)
            return self.data.get(userid)

        raise ValueError('Either userid or login must be supplied')

    def add(self, userid, login, cleartext_password, groups=None):
        self._upgrade()
        salt = get_random_string()
        encrypted_password = pbkdf2(cleartext_password, salt)
        if groups is None:
            groups = []
        newgroups = set()
        for group in groups:
            group = self._convert(group)
            newgroups.add(group)
        userid = self._convert(userid)
        login = self._convert(login)
        info = {
            'login': login,
            'id': userid,
            'salt': salt,
            'password': encrypted_password,
            'groups': newgroups}
        if userid in self.data:
            raise ValueError('User ID "%s" already exists' % userid)
        if login in self.logins:
            raise ValueError('Login "%s" already exists' % login)
        self.logins[login] = userid
        self.data[userid] = info

        for group in newgroups:
            userids = self.groups.get(group, set())
            self.groups[group] = userids  # trigger persistence
            userids.add(userid)

    def remove(self, userid):
        self._upgrade()
        userid = self._convert(userid)
        info = self.data[userid]
        login = info['login']
        del self.logins[login]
        for group in info['groups']:
            userids = self.groups.get(group, [])
            if userid in userids:
                self.groups[group] = userids  # trigger persistence
                userids.remove(userid)
        del self.data[userid]

    def change_password(self, userid, password):
        self._upgrade()
        userid = self._convert(userid)
        info = self.data[userid]
        if 'salt' not in info:
            info['salt'] = get_random_string()
        self.data[userid] = info  # trigger persistence
        info['password'] = pbkdf2(password, info['salt'])

    def change_login(self, userid, login):
        self._upgrade()
        userid = self._convert(userid)
        login = self._convert(login)
        info = self.data[userid]
        old_login = info['login']
        if old_login == login:
            # no change
            return
        if login in self.logins:
            raise ValueError('Login "%s" already exists' % login)
        self.data[userid] = info  # trigger persistence
        info['login'] = login
        self.logins[login] = userid
        del self.logins[old_login]

    def add_user_to_group(self, userid, group):
        self._upgrade()
        userid = self._convert(userid)
        group = self._convert(group)
        info = self.data[userid]
        self.data[userid] = info  # trigger persistence
        info['groups'].add(group)
        userids = self.groups.setdefault(group, set())
        self.groups[group] = userids  # trigger persistence
        userids.add(userid)

    add_group = add_user_to_group

    def remove_user_from_group(self, userid, group):
        self._upgrade()
        userid = self._convert(userid)
        group = self._convert(group)
        info = self.data[userid]
        groups = info['groups']
        if group in groups:
            self.data[userid] = info  # trigger persistence
            groups.remove(group)
        userids = self.groups.get(group)
        if userids is not None:
            if userid in userids:
                self.groups[group] = userids  # trigger persistence
                userids.remove(userid)

    remove_group = remove_user_from_group

    def member_of_group(self, userid, group):
        self._upgrade()
        userid = self._convert(userid)
        group = self._convert(group)
        userids = self.groups.get(group, set())
        return userid in userids

    in_group = member_of_group

    def delete_group(self, group):
        self._upgrade()
        group = self._convert(group)
        userids = self.groups.get(group)
        if userids is not None:
            del self.groups[group]
            for userid in userids:
                info = self.data.get(userid)
                if info is not None:
                    infogroups = info['groups']
                    if group in infogroups:
                        self.data[userid] = info  # trigger persistence
                        infogroups.remove(group)

    def users_in_group(self, group):
        self._upgrade()
        return self.groups.get(group, set())

    def check_password(self, password, userid=None, login=None):
        if userid is None and login is None:
            raise ValueError("Must provide userid or login")
        if userid is not None:
            user = self.get(userid=userid)
        else:
            login = self._convert(login)
            userid = self.logins.get(login)
            user = self.get(login=login)

        if user['password'].startswith('SHA1:'):
            # old style password, need to upgrade but will check it first
            enc_password = get_sha_password(password)
            if strings_same(enc_password, user['password']):
                # upgrade this password...
                salt = get_random_string()
                user.update({
                    'password': pbkdf2(password, salt),
                    'salt': salt
                })
                self.data[userid] = user  # trigger persistence
                return True
            else:
                return False
        else:
            # should be 'pbkdf2' encrypted now
            return strings_same(
                pbkdf2(password, user['salt']),
                user['password'])
