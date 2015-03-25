import unittest

class UsersTests(unittest.TestCase):
    def _getTargetClass(self):
        from karl.models.users import Users
        return Users

    def _makeOne(self):
        return self._getTargetClass()()

    def _verifyPassword(self, users, userid, value):
        from karl.models.users import pbkdf2
        user = users.get(userid)
        self.assertEqual(user['password'],
                         pbkdf2(value, user['salt']))

    def test_class_conforms_to_IUsers(self):
        from zope.interface.verify import verifyClass
        from karl.models.interfaces import IUsers
        verifyClass(IUsers, self._getTargetClass())

    def test_instance_conforms_to_IUsers(self):
        from zope.interface.verify import verifyObject
        from karl.models.interfaces import IUsers
        verifyObject(IUsers, self._makeOne())

    def test_add_and_remove(self):
        from karl.models.users import pbkdf2
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        user = users.get('id')
        expected = {
            'id': 'id',
            'login': 'login',
            'salt': user['salt'],
            'password': pbkdf2('password', user['salt']),
            'groups': set(['group.foo']),
            }
        self.assertEqual(users.logins[u'login'], u'id')
        self.assertEqual(users.data[u'id'], expected)

        users.remove('id')
        self.assertEqual(users.data.get('id'), None)
        self.assertEqual(users.logins.get(u'login'), None)

    def test_add_conflicting_userid(self):
        users = self._makeOne()
        users.add('id1', 'login1', 'password')
        self.assertRaises(ValueError, users.add, 'id1', 'login2', 'password')

    def test_add_conflicting_login(self):
        users = self._makeOne()
        users.add('id1', 'login1', 'password')
        self.assertRaises(ValueError, users.add, 'id2', 'login1', 'password')

    def test_get_userid(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        self.assertEqual(users.get('id')['login'], 'login')

    def test_get_login(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        self.assertEqual(users.get(login='login')['id'], 'id')

    def test_get_neither(self):
        users = self._makeOne()
        self.assertRaises(ValueError, users.get, None, None)

    def test_get_both(self):
        users = self._makeOne()
        self.assertRaises(ValueError, users.get, 'a', 'a')

    def test_get_by_id(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        self.assertEqual(users.get_by_id('id')['login'], 'login')

    def test_get_by_login(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        self.assertEqual(users.get_by_login('login')['id'], 'id')

    def test_change_password(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        users.change_password('id', 'another')
        self._verifyPassword(users, 'id', 'another')

    def test_change_password_unicode(self):
        password = u'an\xf2ther'
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        users.change_password('id', password)
        self._verifyPassword(users, 'id', password)

    def test_change_login(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        users.change_login('id', 'another')
        self.assertEqual(users.get('id')['login'], 'another')
        self.assert_(users.get_by_login('login') is None)
        self.assert_(users.get_by_login('another') is not None)
        # Password should not have changed!
        self._verifyPassword(users, 'id', 'password')

    def test_change_login_unchanged(self):
        users = self._makeOne()
        users.add('id1', 'login1', 'password')
        users.change_login('id1', 'login1')
        self.assertEqual(users.get_by_id('id1')['login'], 'login1')
        self.assert_(users.get_by_login('login1') is not None)

    def test_change_login_conflicting(self):
        users = self._makeOne()
        users.add('id1', 'login1', 'password')
        users.add('id2', 'login2', 'password')
        self.assertRaises(ValueError, users.change_login, 'id2', 'login1')

    def test_add_user_to_group(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        users.add_user_to_group('id', 'another')
        self.assertEqual(users.get('id')['groups'],
                         set(['group.foo', 'another']))
        # Password should not have changed!
        self._verifyPassword(users, 'id', 'password')
        self.assertEqual(users.groups['another'], set(['id']))

    def test_delete_group(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo', 'group.bar'])
        users.add('id2', 'login2', 'password2', groups=['group.foo'])
        users.delete_group('group.foo')
        self.assertEqual(users.get('id')['groups'], set(['group.bar']))
        self.assertEqual(users.get('id2')['groups'], set([]))
        self.failIf('group.foo' in users.groups)
        # Passwords should not have changed!
        self._verifyPassword(users, 'id', 'password')
        self._verifyPassword(users, 'id2', 'password2')

    def test_remove_user_from_group_exists(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        users.remove_user_from_group('id', 'group.foo')
        self.assertEqual(users.get('id')['groups'], set())
        self.assertEqual(users.groups['group.foo'], set([]))
        # Password should not have changed!
        self._verifyPassword(users, 'id', 'password')

    def test_remove_user_from_group_notexists(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=[])
        users.remove_user_from_group('id', 'group.foo')
        self.assertEqual(users.get('id')['groups'], set())
        # Password should not have changed!
        self._verifyPassword(users, 'id', 'password')

    def test_remove_user_from_group_notingroups(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['abc'])
        users.groups['abc'].remove('id')
        users.remove_user_from_group('id', 'abc')
        self.assertEqual(users.get('id')['groups'], set())

    def test_member_of_group(self):
        users = self._makeOne()
        users.add('id', 'login', 'password', groups=['group.foo'])
        self.assertEqual(users.member_of_group('id', 'group.foo'), True)
        self.assertEqual(users.member_of_group('id', 'group.bar'), False)

    def test_users_in_group(self):
        users = self._makeOne()
        users.add('id1', 'login1', 'password', groups=['group.foo'])
        users.add('id2', 'login2', 'password', groups=['group.foo'])
        users.add('id3', 'login3', 'password', groups=['group.none'])
        self.assertEqual(users.users_in_group('group.foo'), set(['id1', 'id2']))

    def test_users_in_group_empty_group(self):
        users = self._makeOne()
        self.assertEqual(users.users_in_group('group.foo'), set())

    def test_upgrade(self):
        from BTrees.OOBTree import OOBTree
        from karl.models.users import pbkdf2
        users = self._makeOne()
        users.add('id1', 'login1', 'password1',
                  groups=['group.foo', 'group.bar'])
        users.add('id2', 'login2', 'password2',
                  groups=['group.biz', 'group.baz'])
        bylogin = OOBTree()
        for userid, info in users.data.items():
            bylogin[info['login']] = info
        users.byid = users.data
        users.bylogin = bylogin
        users.data = None
        users.groups = None
        users.logins = None
        users._upgrade()

        self.assertEqual(len(users.data), 2)

        self.assertEqual(
            users.data[u'id1'],
            {'id': 'id1',
             'login': 'login1',
             'salt': users.data[u'id1']['salt'],
             'password': pbkdf2('password1', users.data[u'id1']['salt']),
             'groups': set([u'group.foo',
                            u'group.bar'])}
            )

        self.assertEqual(
            users.data[u'id2'],
            {'id': 'id2',
             'login': 'login2',
             'salt': users.data[u'id2']['salt'],
             'password': pbkdf2('password2', users.data[u'id2']['salt']),
             'groups': set([u'group.biz',
                            u'group.baz'])}
            )

        self.assertEqual(len(users.logins), 2)
        self.assertEqual(users.logins[u'login1'], u'id1')
        self.assertEqual(users.logins[u'login2'], u'id2')

        self.assertEqual(len(users.groups), 4)
        self.assertEqual(users.groups[u'group.foo'], set([u'id1']))
        self.assertEqual(users.groups[u'group.bar'], set([u'id1']))
        self.assertEqual(users.groups[u'group.biz'], set([u'id2']))
        self.assertEqual(users.groups[u'group.baz'], set([u'id2']))


class DummyUsers:
    closed = False
    def __init__(self, *users):
        self.users = users

    def get(self, userid=None, login=None):
        for user in self.users:
            if user['id'] == userid:
                return user
            if user['login'] == login:
                return user

    def in_group(self, id, group):
        for user in self.users:
            if user['id'] == id:
                return group in user['groups']
        return False

    def get_by_login(self, login):
        return self.get(login=login)
