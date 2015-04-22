from karl.utils import get_setting


def get_access_request_fields(context):
    fields = []
    for field in get_setting(context, 'request_access_fields'):
        field = field.split('|', 1)
        if len(field) == 2:
            fields.append({
                'id': field[0],
                'label': field[1]
                })
        else:
            fields.append({
                'id': field[0],
                'label': field[0]
                })
    return fields
