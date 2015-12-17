from karl.utils import find_profiles
from karl.workflow import to_profile_active
from karl.workflow import to_profile_inactive

import sys

import transaction


def evolve(site):
    """
    reset profile ACL to remove 'view_only' permission (replacing any usage
    with 'view')

    add 'industry' to column in people report
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

    if 'people' in site:
        people = site['people']
        for key in people.keys():
            obj1 = people[key]
            for key2 in obj1.keys():
                obj2 = obj1[key2]
                if not hasattr(obj2, "columns"):
                    continue
                colvals = obj2.columns
                if len(colvals) != 4:  # won't have the default
                    continue
                # if the report contains the default columns, then replace
                # them with the new default columns
                if colvals[0] == 'name' and colvals[1] == 'organization' \
                        and colvals[2] == 'location' and colvals[3] == 'email':
                    obj2.columns = ('name', 'organization', 'location', 'industry', 'email')

    transaction.commit()
