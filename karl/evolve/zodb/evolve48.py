from BTrees.OOBTree import OOBTree


def evolve(site):
    """
    upgrade site settings
    """
    import pdb; pdb.set_trace()
    settings = site._default_settings.copy()
    if hasattr(site, 'footer_html'):
        settings['footer_html'] = site.footer_html
        del site.footer_html
    site.settings = OOBTree(settings)