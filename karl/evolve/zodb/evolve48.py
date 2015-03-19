from BTrees.OOBTree import OOBTree


def evolve(site):
    """
    upgrade site settings
    """
    if not hasattr(site, 'settings'):
        settings = site._default_settings.copy()
        if hasattr(site, 'footer_html'):
            settings['footer_html'] = site.footer_html
            del site.footer_html
        site.settings = OOBTree(settings)
    if not hasattr(site, 'access_requests'):
        site.access_requests = OOBTree()