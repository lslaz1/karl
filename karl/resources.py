from karl.utils import get_static_resources_data
from karl.utils import get_static_url
from karl.utils import is_resource_devel_mode


class StaticResource(object):
    def __init__(self, path, always_include=False, ie_expression=None):
        self.path = path
        self.ie_expression = ie_expression
        self.always_include = always_include


class CSSFile(StaticResource):

    def render(self, request):
        full_path = '%s/%s' % (
            request.application_url.rstrip('/'),
            self.path.lstrip('/'))
        if self.ie_expression:
            return '''<!--[if %s]> <style type="text/css" media="all">@import
  url(%s);</style>
<![endif]-->''' % (self.ie_expression, full_path)
        else:
            return '''<link rel="stylesheet"
href="%s" type="text/css"/>''' % full_path


class JavaScriptResource(StaticResource):

    def __init__(self, path=None, name=None, resource_name=None,
                 always_include=False, ie_expression=None, minPrefix=None):
        self.path = path
        self.name = name
        self.resource_name = resource_name
        self.ie_expression = ie_expression
        self.always_include = always_include

    def render_path(self, path):
        if self.ie_expression:
            return '''<!--[if %s]> <script type="text/javascript" src="%s"></script>
<![endif]-->''' % (self.ie_expression, path)
        else:
            return '''<script type="text/javascript" src="%s"></script>''' % path

    def render(self, request):
        static_url = get_static_url(request)
        resource_devel_mode = is_resource_devel_mode()
        if self.path is not None:
            full_path = '%s/%s' % (
                request.application_url.rstrip('/'),
                self.path.lstrip('/'))
            return self.render_path(full_path)
        elif self.name is not None:
            if resource_devel_mode:
                full_path = '%s/%s.js' % (static_url, self.name)
            else:
                full_path = '%s/%s.min.js' % (static_url, self.name)
            return self.render_path(full_path)
        elif self.resource_name is not None:
            resources = get_static_resources_data()
            if resource_devel_mode:
                try:
                    files = resources['js'][self.resource_name]
                except KeyError:
                    raise RuntimeError(
                        'JS resource "%s" must be defined as a key in resources.json.')
                paths = ['%s/%s' % (static_url, n) for n in files]
            else:
                prefix = resources['minPrefix']
                paths = ['%s/%s%s.min.js' % (static_url, prefix, self.resource_name)]
            return '\n'.join([self.render_path(p) for p in paths])
        else:
            return '<!-- nothing to render here -->'


class Resources(object):

    def __init__(self, key, factory=CSSFile):
        self.key = key
        self.factory = factory
        self.data = {}
        self.order = []

    def add(self, _name, *args, **kwargs):
        self.data[_name] = self.factory(*args, **kwargs)
        if _name not in self.order:
            self.order.append(_name)

    def get(self, name):
        return self.data.get(name)

    def get_all(self, request):
        files = []
        included_here = request.environ.get(self.key, [])
        for name in self.order:
            resource = self.data[name]
            if resource.always_include or name in included_here:
                files.append(resource)
        return files

    def require(self, request, name):
        if self.key not in request.environ:
            request.environ[self.key] = set([])
        request.environ[self.key].add(name)

    def disable(self, request, name):
        if self.key not in request.environ:
            request.environ[self.key] = set([])
        if name in request.environ[self.key]:
            request.environ[self.key].remove(name)
