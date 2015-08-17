from pyramid.url import resource_url

from karl.views.api import TemplateAPI
from karl.utils import find_site


def forbidden(context, request):
    site = find_site(context)
    request.session['came_from'] = request.url
    api = TemplateAPI(context, request, 'Secure Login')
    request.response.status = '200 OK'
    if api.userid:
        login_url = resource_url(site, request, 'login.html')
    else:
        query = {
            'came_from': request.url,
            'reason': 'Not logged in'
        }
        login_url = resource_url(
            site, request, 'login.html', query=query)
    return {
        'api': api,
        'login_form_url': login_url,
        'homepage_url': resource_url(site, request)
    }
