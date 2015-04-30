from persistent import Persistent
from repoze.folder import Folder
from persistent.mapping import PersistentMapping
from ZODB.blob import Blob


class EmailFolder(Folder):
    def __init__(self):
        super(EmailFolder, self).__init__()
        self._paths_to_codes = PersistentMapping()

    def add_image(self, image):
        self._paths_to_codes[image.path] = image.code
        self[image.code] = image

    def find_image(self, path):
        if path in self._paths_to_codes:
            return self[self._paths_to_codes[path]]


class EmailImage(Persistent):
    size = 0

    def __init__(self, path, ct, size):
        from karl.utils import get_random_string
        self.code = get_random_string(25)
        self.blob = Blob()
        self.path = path
        self.ct = ct
        self.size = size