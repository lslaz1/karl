import unittest


class TestOfflineContextURL(unittest.TestCase):

    def setUp(self):
        from pyramid.testing import cleanUp
        cleanUp()

    def tearDown(self):
        from pyramid.testing import cleanUp
        cleanUp()

    def _getTargetClass(self):
        from karl.adapters.url import OfflineContextURL
        return OfflineContextURL

    def _makeContext(self, **kw):
        from pyramid.testing import DummyModel
        return DummyModel(**kw)

    def _makeOne(self, model=None):
        from pyramid.testing import DummyModel
        if model is None:
            model = DummyModel()
        return self._getTargetClass()(model, None)

    def _makeRoot(self):
        from karl.models.interfaces import ISite
        from zope.interface import directlyProvides
        from karl.models.site import Site
        context = self._makeContext(list_aliases={})
        directlyProvides(context, ISite)
        context.settings = Site._default_settings
        return context

    def test_class_conforms_to_IContextURL(self):
        from zope.interface.verify import verifyClass
        from pyramid.interfaces import IContextURL
        verifyClass(IContextURL, self._getTargetClass())

    def test_instance_conforms_to_IContextURL(self):
        from zope.interface.verify import verifyObject
        from pyramid.interfaces import IContextURL
        verifyObject(IContextURL, self._makeOne())

    def test_virtual_root_raises(self):
        url = self._makeOne()
        self.assertRaises(NotImplementedError, url.virtual_root)

    def test___call___no_settings(self):
        from pyramid.testing import DummyModel
        context = DummyModel()
        url = self._makeOne(context)
        self.assertRaises(ValueError, url)

    def test___call___app_url_trailing_slash(self):
        from pyramid.testing import DummyModel
        root = self._makeRoot()
        root.settings['site_url'] = "http://offline.example.com/app/"
        context = root['foo'] = DummyModel()
        url = self._makeOne(context)
        self.assertEqual(url(), 'http://offline.example.com/app/foo')

    def test___call___no_parent(self):
        from karl.testing import registerSettings
        registerSettings()
        root = self._makeRoot()
        url = self._makeOne(root)
        self.assertEqual(url(), 'http://offline.example.com/app/')

    def test___call___w_parent(self):
        from pyramid.testing import DummyModel
        from karl.testing import registerSettings
        registerSettings()
        root = self._makeRoot()
        context = root['foo'] = DummyModel()
        url = self._makeOne(context)
        self.assertEqual(url(), 'http://offline.example.com/app/foo')

    def test___call___w_parent_chain(self):
        from pyramid.testing import DummyModel
        from karl.testing import registerSettings
        registerSettings()
        root = self._makeRoot()
        foo = root['foo'] = DummyModel()
        context = foo['bar'] = DummyModel()
        url = self._makeOne(context)
        self.assertEqual(url(), 'http://offline.example.com/app/foo/bar')
