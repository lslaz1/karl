
def get_tinymce_options(api):
    document_base_url = api.request.application_url
    # tinymce requires that the base url end with a '/'
    if document_base_url[-1] != '/':
        document_base_url += '/'
    return {
        # disable tinymce upload tab, do not have time to implement
        'upload': None,
        'tiny': {
            'relative_urls': False,
            'remove_script_host': False,
            'document_base_url': document_base_url,
            'browser_spellcheck': True,
            'content_css': api.get_css_resource('karl-theme').path,  # noqa
            'theme': '-modern',
            'plugins': [
                'advlist autolink lists charmap print preview anchor',
                'searchreplace visualblocks code fullscreen',
                'insertdatetime media table contextmenu plonelink ploneimage',
            ],
            'menubar': 'edit table format tools view insert',
            'toolbar': 'styleselect | bold italic | '
                       'alignleft aligncenter alignright alignjustify | '
                       'bullist numlist outdent indent | '
                       'unlink plonelink ploneimage',
            'height': 400
        },
        'relatedItems': {
            # UID attribute is required here since we're working with related items
            'batchSize': 20,
            'basePath': '/',
            'vocabularyUrl': api.request.application_url + '/vocabulary.json',
            'width': 400,
            'placeholder': 'Search for item on site...'
        },
        'folderTypes': ['Folder'],
        'linkableTypes': ['Image', 'File', 'Folder', 'Page'],
        'prependToScalePart': '/thumb/',
        'appendToOriginalScalePart': '/dl',
        'defaultScale': 'large',
        'scales': [{
                'part': '32x32.gif',
                'name': 'icon',
                'label': 'Icon(32x32)'
            }, {
                'part': '128x128.gif',
                'name': 'thumb',
                'label': 'Thumb(128x128)'
            }, {
                'part': '200x200.gif',
                'name': 'mini',
                'label': 'Mini(200x200)'
            }, {
                'part': '400x400.gif',
                'name': 'preview',
                'label': 'Preview(400x400)'
            }, {
                'part': '768x768.gif',
                'name': 'large',
                'label': 'Large(768x768)'
            }],
    }
