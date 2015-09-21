from BTrees.OOBTree import OOBTree


def evolve(site):
    """
    add new site attribute
    """
    if not hasattr(site, 'email_templates'):
        site.email_templates = OOBTree()
