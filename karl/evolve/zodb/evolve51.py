from datetime import datetime


def evolve(site):
    """
    Add the IPhoto marker interface to profile and news item photos.
    """
    invitations = site['invitations']
    for invite in invitations.values():
        invite.created_on = datetime.utcnow()
