from pyramid.security import Allow  # noqa
from pyramid.security import Deny
from pyramid.security import Everyone
from pyramid.security import AllPermissionsList

VIEW = 'view'
EDIT = 'edit'
CREATE = 'create'
DELETE = 'delete'
DELETE_COMMUNITY = 'delete community'
EMAIL = 'email'
MODERATE = 'moderate'
ADMINISTER = 'administer'
COMMENT = 'comment'

GUEST_PERMS = (VIEW, COMMENT)
MEMBER_PERMS = GUEST_PERMS + (EDIT, CREATE, DELETE)
MODERATOR_PERMS = MEMBER_PERMS + (MODERATE,)
ADMINISTRATOR_PERMS = MODERATOR_PERMS + (ADMINISTER, DELETE_COMMUNITY, EMAIL)

ALL = AllPermissionsList()
NO_INHERIT = (Deny, Everyone, ALL)


def get_groups(identity, request):
    if 'groups' in identity:
        return identity['groups']
