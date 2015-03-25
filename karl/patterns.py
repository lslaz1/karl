

def get_tinymce_options(context, request):
    return {
        # disable tinymce upload tab, do not have time to implement
        'upload': None,
        'tiny': {
            'content_css': '/static/dist/tinymce-builded/js/tinymce/skins/lightgray/content.min.css',  # noqa
            'theme': '-modern',
            'plugins': [
                'advlist autolink lists charmap print preview anchor',
                'searchreplace visualblocks code fullscreen',
                'insertdatetime media table contextmenu paste plonelink ploneimage',
            ],
            'menubar': 'edit table format tools view insert',
            'toolbar': 'undo redo | styleselect | bold italic | '
                       'alignleft aligncenter alignright alignjustify | '
                       'bullist numlist outdent indent | '
                       'unlink plonelink ploneimage',
            'height': 400
        },
        'relatedItems': {
            # UID attribute is required here since we're working with related items
            'batchSize': 20,
            'basePath': '/',
            'vocabularyUrl': '/vocabulary.json',
            'width': 400,
            'placeholder': 'Search for item on site...'
        },
        'folderTypes': ['Folder'],
        'linkableTypes': ['Image', 'File', 'Folder', 'Page'],
        'prependToScalePart': '/thumb/',
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
            }]
    }