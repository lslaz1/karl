import json
from karl.models.interfaces import ICatalogSearch
import itertools
from karl.content.interfaces import IImage, ICommunityFile
from repoze.folder.interfaces import IFolder
from pyramid.security import effective_principals
from pyramid.url import resource_url
from pyramid.traversal import resource_path
from karl.utils import find_catalog
from pyramid.traversal import find_resource


DEFAULT_BATCH = {
    'page': 1,
    'size': 20
}

type_name_mapping = {
    'Image': IImage,
    'File': ICommunityFile,
    'Folder': IFolder
}

image_mimetypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif']

def parse_query(query):
    result = {}
    for criteria in query['criteria']:
        name = criteria['i']
        value = criteria['v']
        if name == 'Type':
            new_value = []
            if type(value) not in (list, tuple):
                value = [value]
            for v in value:
                if v in type_name_mapping:
                    new_value.append(type_name_mapping[v])
            value = new_value
            name = 'interfaces'
            if IImage in value:
                result['mimetype'] = {
                    'query': image_mimetypes,
                    'operator': 'or'
                }
        elif name == 'path':
            split = value.split('::')
            if len(split) == 2:
                path = split[0]
                depth = split[1]
            else:
                path = value
                depth = 1
            value = {
                'query': path,
                'depth': depth
            }
        result[name] = value
    return result


_attribute_mapping = {
    'id': '__name__',
    'Title': 'title',
    'Description': 'description'
}

def ResovlerFactory(context):
    catalog = find_catalog(context)
    address = catalog.document_map.address_for_docid
    def resolver(docid):
        path = address(docid)
        if path is None:
            return None
        try:
            return find_resource(context, path)
        except KeyError:
            return None
    return resolver


def vocabulary_view(context, request):
    try:
        attributes = json.loads(request.params.get('attributes', '["title", ""]'))
    except:
        attributes = ['title', 'id']
    if 'UID' in attributes:
        # always put in anyways
        attributes.remove('UID')

    try:
        batch = json.loads(request.params.get('batch'))
    except:
        batch = DEFAULT_BATCH

    query = json.loads(request.params['query'])
    criteria = parse_query(query)

    if 'UID' in criteria:
        resolver = ResovlerFactory(context)
        docids = criteria['UID']
        if type(docids) not in (list, tuple):
            docids = [docids]
        # convert to ints
        new_docids = []
        for docid in docids:
            try:
                new_docids.append(int(docid))
            except:
                pass
        docids = new_docids
        numdocs = len(docids)
    else:
        criteria['allowed'] = {
            'query': effective_principals(request),
            'operator': 'or'
        }
        searcher = ICatalogSearch(context)
        numdocs, docids, resolver = searcher(**criteria)

    if batch and ('size' not in batch or 'page' not in batch):
        batch = DEFAULT_BATCH
    if batch:
        # must be slicable for batching support
        page = int(batch['page'])
        # page is being passed in is 1-based
        start = (max(page - 1, 0)) * int(batch['size'])
        end = start + int(batch['size'])
        # Try __getitem__-based slice, then iterator slice.
        # The iterator slice has to consume the iterator through
        # to the desired slice, but that shouldn't be the end
        # of the world because at some point the user will hopefully
        # give up scrolling and search instead.
        try:
            docids = docids[start:end]
        except TypeError:
            docids = itertools.islice(docids, start, end)

    # build result items
    items = []
    for docid in docids:
        result = resolver(docid)
        if result is None:
            continue
        data = {
            'UID': docid
        }
        for attribute in attributes:
            attr = attribute
            if attribute in _attribute_mapping:
                attr = _attribute_mapping[attribute]
            if attr == 'Type':
                value = 'Page'
                if IImage.providedBy(result):
                    value = 'Image'
                elif ICommunityFile.providedBy(result):
                    value = 'File'
                elif IFolder.providedBy(result):
                    value = 'Folder'
            elif attr == 'getURL':
                value = resource_url(result, request)
            elif attr == 'path':
                # a bit weird here...
                value = resource_path(result, request).split('/GET')[0]
            else:
                value = getattr(result, attr, None)
            data[attribute] = value
        items.append(data)
    return {
        'results': items,
        'total': numdocs
    }
