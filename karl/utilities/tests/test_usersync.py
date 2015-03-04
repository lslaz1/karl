import mock
import StringIO

try:
    import unittest2 as unittest
except ImportError:
    import unittest

from pyramid import testing


class UserSyncTests(unittest.TestCase):

    def setUp(self):
        self.context = context = testing.DummyResource()
        context.users = mock.Mock()
        context['profiles'] = testing.DummyResource()

    def make_one(self):
        from karl.utilities.usersync import UserSync as test_class
        return test_class(self.context)

    @mock.patch('karl.utilities.usersync.urllib2')
    def test_download_userdata(self, urllib2):
        urllib2.urlopen.return_value = StringIO.StringIO('"TEST"')
        testobj = self.make_one()
        self.assertEqual(testobj.download_userdata('URL'), 'TEST')
        urllib2.urlopen.assert_called_once_with('URL')

    @mock.patch('karl.utilities.usersync.urllib2')
    @mock.patch('karl.utilities.usersync.base64.encodestring',
                lambda s: 'base64:' + s)
    def test_download_userdata_with_credentials(self, urllib2):
        urllib2.urlopen.return_value = StringIO.StringIO('"TEST"')
        testobj = self.make_one()
        self.assertEqual(
            testobj.download_userdata('URL', 'user', 'password'),
            'TEST')
        urllib2.Request.assert_called_once_with('URL')
        request = urllib2.urlopen.call_args[0][0]
        request.add_header.assert_called_once_with(
            "Authorization", "Basic base64:user:password")

    @mock.patch('karl.utilities.usersync.urllib2')
    def test_download_userdata_with_timestamp(self, urllib2):
        urllib2.urlopen.return_value = StringIO.StringIO('"TEST"')
        self.context.usersync_timestamp = 'TIMESTAMP'
        testobj = self.make_one()
        self.assertEqual(testobj.download_userdata('URL'), 'TEST')
        urllib2.urlopen.assert_called_once_with('URL?timestamp=TIMESTAMP')

    @mock.patch('karl.utilities.usersync.urllib2')
    def test_download_userdata_duplicate(self, urllib2):
        import hashlib
        from karl.utilities.usersync import DUPLICATE
        urllib2.urlopen.return_value = StringIO.StringIO('"TEST"')
        self.context.usersync_sha1 = hashlib.sha1('"TEST"').digest()
        testobj = self.make_one()
        self.assertEqual(testobj.download_userdata('URL'), DUPLICATE)
        urllib2.urlopen.assert_called_once_with('URL')

    @mock.patch('karl.utilities.usersync.get_workflow')
    @mock.patch('karl.utilities.usersync.create_content')
    def test_syncusers_create_user(self, create_content, get_workflow):
        from karl.models.interfaces import IProfile
        self.context.usersync_timestamp = 'FOO'
        data = {'users': [
            {'username': 'fred',
             'firstname': 'Fred',
             'lastname': 'Flintstone',
             'email': 'fred@bedrock',
             'password': 'SHA1:gobbledygook',
             'login': 'mrfred',
             'groups': ['group.People', 'group.Prehistoric'],
             'phone': '919-555-1212',
             'extension': '23',
             'fax': '818-555-1212',
             'department': 'digging',
             'position': 'digger',
             'organization': 'Diggers',
             'location': 'Bedrock',
             'country': 'Pangea',
             'websites': ['http://bedrock.test'],
             'languages': ['human', 'dinosaur'],
             'office': '000',
             'room_no': '111',
             'biography': 'Born along time ago.',
             'date_format': 'en_OLD'}
        ]}
        testobj = self.make_one()
        testobj.sync(data)
        self.context.users.add.assert_called_once_with(
            'fred', 'mrfred', 'SHA1:gobbledygook',
            ['group.People', 'group.Prehistoric'], encrypted=True)
        fred = self.context['profiles']['fred']
        self.assertEqual(fred.firstname, 'Fred')
        self.assertEqual(fred.lastname, 'Flintstone')
        self.assertEqual(fred.email, 'fred@bedrock')
        self.assertEqual(fred.phone, '919-555-1212')
        self.assertEqual(fred.extension, '23')
        self.assertEqual(fred.fax, '818-555-1212')
        self.assertEqual(fred.department, 'digging')
        self.assertEqual(fred.organization, 'Diggers')
        self.assertEqual(fred.location, 'Bedrock')
        self.assertEqual(fred.country, 'Pangea')
        self.assertEqual(fred.websites, ['http://bedrock.test'])
        self.assertEqual(fred.languages, ['human', 'dinosaur'])
        self.assertEqual(fred.office, '000')
        self.assertEqual(fred.room_no, '111')
        self.assertEqual(fred.biography, 'Born along time ago.')
        self.assertEqual(fred.date_format, 'en_OLD')
        self.assertIs(fred.usersync_managed, True)
        create_content.assert_called_once_with(IProfile)
        self.assertFalse(hasattr(self.context, 'usersync_timestamp'))
        get_workflow.assert_called_once_with(IProfile, 'security', fred)
        workflow = get_workflow.return_value
        workflow.transition_to_state.assert_called_once_with(
            fred, None, 'active')

    @mock.patch('karl.utilities.usersync.objectEventNotify')
    def test_sync_users_update(self, notify):
        data = {'users': [
            {'username': 'fred',
             'login': 'flintstone',
             'email': 'flintstone@bedrock'}
        ]}
        self.context['profiles']['fred'] = fred = mock.Mock(
            security_state='active')
        self.context.users.get.return_value = {
            'login': 'fred',
            'groups': [],
            'password': 'SHA1:gobbledygook'
        }
        testobj = self.make_one()
        testobj.sync(data)
        self.assertEqual(fred.email, 'flintstone@bedrock')
        self.assertIs(fred.usersync_managed, True)
        self.context.users.get.assert_called_once_with('fred')
        self.context.users.add.assert_called_once_with(
            'fred', 'flintstone', 'SHA1:gobbledygook', [], encrypted=True)
        self.assertEquals(notify.call_count, 2)

    def test_sync_users_save_timestamp(self):
        data = {
            'timestamp': 'THETIMESTAMP',
            'users': [],
        }
        testobj = self.make_one()
        testobj.sync(data)
        self.assertEqual(self.context.usersync_timestamp, 'THETIMESTAMP')

    @mock.patch('karl.utilities.usersync.get_workflow')
    @mock.patch('karl.utilities.usersync.objectEventNotify')
    def test_sync_users_deactivate_user(self, notify, get_workflow):
        from karl.models.interfaces import IProfile
        data = {'users': [
            {'username': 'fred',
             'active': False}
        ]}
        self.context['profiles']['fred'] = fred = mock.Mock(
            security_state='active')
        self.context.users.get.return_value = {
            'login': 'fred',
            'password': 'password',
            'groups': []}
        testobj = self.make_one()
        testobj.sync(data)
        self.context.users.remove.assert_called_once_with('fred')
        self.assertEquals(notify.call_count, 2)
        get_workflow.assert_called_once_with(IProfile, 'security', fred)
        workflow = get_workflow.return_value
        workflow.transition_to_state.assert_called_once_with(
            fred, None, 'inactive')

    @mock.patch('karl.utilities.usersync.get_workflow')
    @mock.patch('karl.utilities.usersync.objectEventNotify')
    def test_sync_users_reactivate_user(self, notify, get_workflow):
        from karl.models.interfaces import IProfile
        data = {'users': [
            {'username': 'fred',
             'password': 'password',
             'active': True},
            {'username': 'barney'}
        ]}
        self.context['profiles']['fred'] = fred = mock.Mock(
            security_state='inactive')
        self.context['profiles']['barney'] = mock.Mock(
            security_state='inactive')
        self.context.users.get.return_value = None
        testobj = self.make_one()
        testobj.sync(data)
        self.context.users.add.assert_called_once_with(
            'fred', 'fred', 'password', [], encrypted=True)
        self.assertEquals(notify.call_count, 4)
        get_workflow.assert_called_once_with(IProfile, 'security', fred)
        workflow = get_workflow.return_value
        workflow.transition_to_state.assert_called_once_with(
            fred, None, 'active')

    @mock.patch('karl.utilities.usersync.get_workflow')
    @mock.patch('karl.utilities.usersync.objectEventNotify')
    def test_sync_users_deactivate_missing(self, notify, get_workflow):
        from karl.models.interfaces import IProfile
        data = {'deactivate_missing': True, 'users': [{'username': 'barney'}]}
        self.context['profiles']['fred'] = fred = mock.Mock(
            security_state='active', usersync_managed=True)
        self.context['profiles']['barney'] = mock.Mock(
            security_state='active', usersync_managed=True)
        self.context['profiles']['wilma'] = mock.Mock(
            security_state='active', usersync_managed=False)
        self.context.users.get.return_value = {
            'login': 'fred',
            'password': 'password',
            'groups': []}
        testobj = self.make_one()
        testobj.sync(data)
        self.assertEqual(self.context.users.remove.call_args, (('fred',), {}))
        get_workflow.assert_called_once_with(IProfile, 'security', fred)
        workflow = get_workflow.return_value
        workflow.transition_to_state.assert_called_once_with(
            fred, None, 'inactive')

    def test_sync_users_unrecognized_key(self):
        data = {'foo': 'bar', 'users': []}
        testobj = self.make_one()
        with self.assertRaises(ValueError):
            testobj.sync(data)

    def test_sync_users_missing_username(self):
        data = {'foo': 'bar', 'users': [{}]}
        testobj = self.make_one()
        with self.assertRaises(ValueError):
            testobj.sync(data)

    @mock.patch('karl.utilities.usersync.get_workflow')
    @mock.patch('karl.utilities.usersync.objectEventNotify')
    def test_sync_users_reactivate_missing_password(self, notify, get_workflow):
        data = {'users': [
            {'username': 'fred',
             'active': True}
        ]}
        self.context['profiles']['fred'] = mock.Mock(security_state='inactive')
        testobj = self.make_one()
        with self.assertRaises(ValueError):
            testobj.sync(data)

    @mock.patch('karl.utilities.usersync.objectEventNotify')
    def test_sync_users_unrecognized_user_key(self, notify):
        data = {'foo': 'bar', 'users': [{'username': 'fred', 'foo': 'bar'}]}
        self.context['profiles']['fred'] = mock.Mock(security_state='inactive')
        testobj = self.make_one()
        with self.assertRaises(ValueError):
            testobj.sync(data)

    def test_sync_users_missing_keys(self):
        data = {'foo': 'bar', 'users': [{'username': 'fred'}]}
        testobj = self.make_one()
        with self.assertRaises(ValueError):
            testobj.sync(data)

    @mock.patch('karl.utilities.usersync.UserSync.download_userdata')
    @mock.patch('karl.utilities.usersync.UserSync.sync')
    def test_call(self, sync, download):
        download.return_value = 'DATA'
        testobj = self.make_one()
        testobj('url', 'username', 'password')
        download.assert_called_once_with('url', 'username', 'password')
        sync.assert_called_once_with('DATA')

    @mock.patch('karl.utilities.usersync.UserSync.download_userdata')
    @mock.patch('karl.utilities.usersync.UserSync.sync')
    def test_call_duplicate(self, sync, download):
        from karl.utilities.usersync import DUPLICATE
        download.return_value = DUPLICATE
        testobj = self.make_one()
        testobj('url', 'username', 'password')
        download.assert_called_once_with('url', 'username', 'password')
        self.assertFalse(sync.called)
