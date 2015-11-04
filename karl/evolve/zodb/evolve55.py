from BTrees.OOBTree import OOBTree


def evolve(site):
    """
    add new site attribute
    """
    if not hasattr(site, 'email_templates'):
        site.email_templates = OOBTree()

        accept_template = {'body': '''<p>Your access request has been approved<p>''',
                           'Subject': 'Please join {{system_name}}',
                           'template_name': 'Accept',
                           'selected_list': [],
                           'sendtouser': 'yes',
                           'sendtoadmins': 'yes'}
        site.email_templates['Accept'] = accept_template

        deny_template = {'body': u'''<html><body>
        <p>Hello {{requestor_name}},</p>
        <p>Your access request has been denied. Please read the guidelines on
           requesting access to {{system_name}}</p>
        </body></html>''',
                         'Subject': 'Access Request to {{system_name}} has been denied',
                         'template_name': 'Deny',
                         'selected_list': [],
                         'sendtouser': 'yes',
                         'sendtoadmins': 'yes'}
        site.email_templates['Deny'] = deny_template

        followup_template = {'body': 'Follow up for {{requestor_name}} - {{requestor_email}}',
                             'Subject': 'Follow up regarding request from {{requestor_email}',
                             'template_name': 'Follow_up',
                             'selected_list': [],
                             'sendtouser': 'no',
                             'sendtoadmins': 'yes'}
        site.email_templates['Follow Up'] = followup_template

