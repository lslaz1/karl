from pyramid.response import Response


def email_image_view(context, req):
    f = context.blob.open()
    headers = [
        ('Content-Type', 'image/%s' % context.ct),
        ('Content-Length', str(context.size)),
    ]

    headers.append(
        ('Content-Disposition', 'filename=image.jpg')
    )

    response = Response(headerlist=headers, app_iter=f)
    return response