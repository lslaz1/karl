from BTrees.OOBTree import OOBTree


def evolve(site):
    site.failed_login_attempts = OOBTree()
