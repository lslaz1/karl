from pyramid.response import Response

def show_bootswatch_theme(self, context, request):
	theme = self.context.settings['bootswatch_theme_css']
	import pdb; pdb.set_trace()
	headers = [
        ('Content-Type', 'text/css'),
    ]

	response = Response(headerlist=headers, body=theme)
	return response