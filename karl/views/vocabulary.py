import json
import itertools
from karl.content.interfaces import IImage, ICommunityFile
from repoze.folder.interfaces import IFolder
from pyramid.security import effective_principals
from pyramid.url import resource_url
from pyramid.traversal import resource_path
from karl.utils import find_catalog
from pyramid.traversal import find_resource
from repoze.catalog.query import (
    NotEq, And, Eq, Any)


DEFAULT_BATCH = {
    'page': 1,
    'size': 20
}

_type_name_mapping = {
    'Image': IImage,
    'File': ICommunityFile,
    'Folder': IFolder
}
_image_mimetypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif']
_index_mapping = {
    'SearchableText': 'texts',
    'Title': 'title'
}
_attribute_mapping = {
    'id': '__name__',
    'Title': 'title',
    'Description': 'description'
}


def normalize_query(query):
    result = {}
    for criteria in query['criteria']:
        result[criteria['i']] = criteria['v']
    return result


def parse_query(query):
    result = []
    for name, value in query.items():
        if name in ('Type', 'portal_type'):
            new_value = []
            if type(value) not in (list, tuple):
                value = [value]
            for v in value:
                if v in _type_name_mapping:
                    new_value.append(_type_name_mapping[v])
            value = new_value
            if IImage in value:
                result.append(Any('mimetype', _image_mimetypes))
            query = Any('interfaces', value)
        elif name == 'path':
            split = value.split('::')
            if len(split) == 2:
                path = split[0]
                depth = split[1]
            else:
                path = value
                depth = 1
            query = Eq(name, {
                'query': path,
                'depth': int(depth)
            })
        elif name in _index_mapping:
            name = _index_mapping[name]
            query = Eq(name, value)
        else:
            query = Eq(name, value)
        result.append(query)
    return result


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
        attributes = json.loads(request.params.get('attributes', '["title", "id"]'))
    except:
        attributes = ['title', 'id']
    if 'UID' in attributes:
        # always put in anyways
        attributes.remove('UID')

    try:
        batch = json.loads(request.params.get('batch'))
    except:
        batch = DEFAULT_BATCH

    query = normalize_query(json.loads(request.params['query']))
    criteria = parse_query(query)

    resolver = ResovlerFactory(context)
    if 'UID' in query:
        docids = query['UID']
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
        criteria.append(Any('allowed', effective_principals(request)))
        if 'title' not in query:
            # we default to requiring a title in these results or
            # else we get a bunch of junky results
            criteria.append(NotEq('title', ''))
        catalog = find_catalog(context)
        numdocs, docids = catalog.query(And(*criteria))

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
            if attr in ('Type', 'portal_type'):
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
