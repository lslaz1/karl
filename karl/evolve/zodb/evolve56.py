from karl.utils import find_profiles
from karl.workflow import to_profile_active
from karl.workflow import to_profile_inactive

import sys

import transaction


def evolve(site):
    """
    reset profile ACL to remove 'view_only' permission (replacing any usage
    with 'view')
    """

    def out(msg):
        sys.stderr.write(msg)
        sys.stderr.write('\n')
        sys.stderr.flush()

    acount = 0
    icount = 0
    ucount = 0
    profiles = find_profiles(site)
    for docid, profile in profiles.items():
        state = getattr(profile, 'security_state', None)
        if state == "active":
            to_profile_active(profile, None)
            acount += 1
        elif state == "inactive":
            to_profile_inactive(profile, None)
            icount += 1
        else:
            ucount += 1
    out("%s affected, %s active, %s inactive, %s unknown" % (
        acount+icount, acount, icount, ucount))
    transaction.commit()
