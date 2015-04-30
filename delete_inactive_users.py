from karl.utils import find_users
from karl.models.interfaces import ICatalogSearch
from karl.models.interfaces import IProfile
from karl.utilities.rename_user import rename_user
import transaction

root._p_jar.sync()
users = find_users(root)
search = ICatalogSearch(root)
count, docids, resolver = search(interfaces=[IProfile])

inactive = []
for docid in docids:
    profile = resolver(docid)
    if profile.security_state == 'inactive':
        inactive.append(profile.__name__)


print str(len(inactive))
for id in inactive:
    rename_user(root, id, 'admin', merge=True)





transaction.commit()

