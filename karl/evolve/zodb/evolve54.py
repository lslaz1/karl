from BTrees.OOBTree import OOBTree


def evolve(site):
    """
    add new site attribute
    """

    if not hasattr(site, 'denial_tracker'):
        site.denial_tracker = OOBTree()
