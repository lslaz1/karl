from pyramid.chameleon_zpt import renderer_factory
import pkg_resources
from pyramid.renderers import RendererHelper


class AddonRendererFactoryFactory(object):

    def __init__(self, packages=[]):
        self.packages = packages

    def __call__(self, info):
        # Does this template exist
        name = info.name
        if ':' in name:
            name = name[name.index(':') + 1:]
        for package in reversed(self.packages):
            if pkg_resources.resource_exists(package.__name__, name):
                return renderer_factory(RendererHelper(
                    name, package, info.registry))

        # default to current package
        return renderer_factory(info)
