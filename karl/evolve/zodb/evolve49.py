from repoze.lemonade.content import create_content
from karl.models.interfaces import IInvitationsFolder


def evolve(site):
    """
    upgrade site settings
    """
    if 'invitations' in site:
        del site['invitations']
    if hasattr(site, 'invitations'):
        del site.invitations
    site['invitations'] = create_content(IInvitationsFolder)
