from karl.utils import find_profiles


def evolve(site):
    """
    Add 'industry' as a profile setting, and add 'navigation_list' as a
    site setting
    """

    profiles = find_profiles(site)
    for key in profiles:
        profile = profiles[key]
        if not hasattr(profile, 'industry'):
            profile.industry = ''

    if 'navigation_list' not in site.settings:
        site.settings['navigation_list'] = "\n".join([
            "Tags|/tagcloud.html",
            "People|/people",
            "Communities|/communities",
            "Feeds|/contentfeeds.html",
        ])
