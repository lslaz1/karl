from karl.utilities.interfaces import IUserLinks
from zope.interface import implementer


@implementer(IUserLinks)
def user_links(api):
    links = []
    if api.can_email and not api.user_is_admin:
        links.append({
            'url': '%s/email_users.html' % api.app_url,
            'title': 'Email'
        })
    if api.user_is_admin:
        links.append({
            'url': api.admin_url,
            'title': 'Admin'
        })
    links.extend([{
        'url': api.home_url,
        'title': 'Home'
    }, {
        'url': api.profile_url,
        'title': 'My Profile'
    }, {
        'url': '%s/logout.html' % api.app_url,
        'title': 'Logout'
    }])
    return links