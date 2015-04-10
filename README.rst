Introduction
============

Karl Project


INI Configuration Values
------------------------

Not all but these are what are specific to the karl app(excluding used plugins)

- pgtextindex.dsn
- pgtextindex.table
- pgtextindex.ts_config
- pgtextindex.maxlen
- system_user
- mail_white_list
- postoffice.bounce_from_email
- postoffice.queue
- zodbconn.uri.postoffice
- syslog_view
- syslog_view_instances
- logs_view
- statistics_folder
- kerberos
- forgot_password_url


Cronjobs/processes to setup
---------------------------

- send mail from mail directory
- send digest emails
- consume mail
- statistics


Workflow
========

Full Access:

 - Admins can administer, delete community, email, view, comment, edit, create and delete
 - Moderators can moderate, view, comment, edit, create and delete
 - Members can view, comment, edit, create and delete
 - Authenticated can view, comment, edit, create and delete

Public View:

 - Admins can administer, delete community, email, view, comment, edit, create and delete
 - Moderators can moderate, view, comment, edit, create and delete
 - Members can view, comment, edit, create and delete
 - Staff can view, comment, edit, create and delete
 - Authenticated can view and comment

Private:

 - Admins can administer, delete community, email, view, comment, edit, create and delete
 - Moderators can moderate, view, comment, edit, create and delete
 - Members can view, comment, edit, create and delete
