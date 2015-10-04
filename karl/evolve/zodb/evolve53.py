from karl.utils import find_profiles


def evolve(site):
    """
    Add 'show_all_users' to site settings
    """

    if 'show_all_users' not in site.settings:
        site.settings['show_all_users'] = False
