# Copyright (C) 2008-2009 Open Society Institute
#               Thomas Moroz: tmoroz@sorosny.org
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License Version 2 as published
# by the Free Software Foundation.  You may not use, modify or distribute
# this program under any other version of the GNU General Public License.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

"""Add or remove KARL site announcements:

  site_announce list
  site_announce add --text=<text>
  site_announce remove --id=<id, displayed in `list`>
  site_announce clear-all
  site_announce clear-old --date=<date>
"""

import argparse
from datetime import datetime
import hashlib
import sys

from persistent.list import PersistentList
from persistent.mapping import PersistentMapping

from karl.scripting import get_default_config
from karl.scripting import open_root


import transaction


def valid_date(dtstr):
    try:
        return datetime.strptime(dtstr, "%Y/%m/%d")
    except:
        msg = "Not a valid date (must be in YYYY/MM/DD format, " \
              "eg '1984-01-26'): {}".format(dtstr)
        raise argparse.ArgumentTypeError(msg)


def do_list(args, root):
    if not hasattr(root, 'site_announcements') or len(root.site_announcements) <= 0:
        print "No active site announcements."
    else:
        if args.verbose:
            print "Printing all current site announcements, newest first:"
            print ""
        for i, annc in enumerate(root.site_announcements):
            print "{}: ({}) {}".format(i, annc['added'].strftime("%x"), annc['content'])
            if args.verbose:
                print ""


def do_add(args, root):
    if args.text is None or args.text.strip() == "":
        raise Exception("When adding an announcement, the `--text` parameter "
                        "must be given")

    if not hasattr(root, 'site_announcements'):
        root.site_announcements = PersistentList()
    annc = PersistentMapping()
    annc["content"] = args.text
    annc["added"] = datetime.now()
    annc["hash"] = hashlib.md5("{}{}".format(args.text, annc["added"]).encode()).hexdigest()
    root.site_announcements.insert(0, annc)

    if args.verbose:
        print "Added 0: [{}] {}".format(annc["added"].strftime("%x"), annc["content"])
        print ""
        do_list(args, root)


def do_remove(args, root):
    if args.id is None:
        raise Exception("When removing an announcement, the `--id` parameter "
                        "must be given (id's can be found by the `list` "
                        "command).")

    if not hasattr(root, 'site_announcements'):
        if args.verbose:
            print "No announcements available to remove."
        return

    try:
        val = root.site_announcements[args.id]
        root.site_announcements.remove(val)
        if args.verbose:
            print "Removed [{}] {}".format(
                val["added"].strftime("%x"),
                val["content"])
            print ""
            do_list(args, root)
    except IndexError:
        raise Exception("Invalid ID value.")


def do_clearall(args, root):
    if not hasattr(root, 'site_announcements'):
        if args.verbose:
            print "No announcements to remove."
        return

    root.site_announcements = PersistentList()
    if args.verbose:
        print "All announcements cleared."


def do_cleardate(args, root):
    if args.cleardate is None:
        raise Exception("When clearing announcements by date,  the `--date` "
                        "parameter must be given.")

    if not hasattr(root, 'site_announcements'):
        if args.verbose:
            print "No announcements to clear."
        return

    forremoval = []
    for annc in root.site_announcements:
        if annc["added"] < args.cleardate:
            forremoval.append(annc)
    for annc in forremoval:
        if args.verbose:
            print "Removing [{}] {}".format(annc["added"], annc["content"])
        root.site_announcements.remove(annc)

    if args.verbose:
        print ""
        print "Removed {} announcement{}.".format(
            len(forremoval),
            "s" if len(forremoval) > 1 else "")
        print ""
        do_list(args, root)


def main():
    parser = argparse.ArgumentParser(
        description="Add or remove KARL site-wide announcements",
        usage="%(prog)s command [options]")
    parser.add_argument('-C', '--config', dest="config",
                        help="Specify a paster config file. Defaults to "
                             "$CWD/etc/karl.ini",
                        required=False, default=None)
    parser.add_argument('command', action='store',
                        help='list, add, remove, clear-all, or clear-old',
                        default='list')
    parser.add_argument('--text', action='store', dest='text',
                        help='Text to add as a site announcement. Used only '
                             'with the `add` command',
                        required=False, default=None)
    parser.add_argument('--id', action='store', dest='id', type=int,
                        help='ID (shown in `list` command) of announcement to '
                             'remove. Used only with `remove` command.',
                        required=False, default=None)
    parser.add_argument('--date', action='store', type=valid_date,
                        help='Any site action added previous to this date '
                             '(YYYY/MM/DD) will be removed. Used only with '
                             'the `clear-date` command.',
                        dest='cleardate', required=False, default=None)
    parser.add_argument('-n', '--dry-run', action='store_true', default=False,
                        help='Do everything except commit changes.',
                        dest='dryrun', required=False)
    parser.add_argument('-v', '--verbose', action='store_true', default=False,
                        help='Print more information to stdout',
                        required=False, dest='verbose')

    args = parser.parse_args()

    # CONFIG/SITE-CONTEXT
    config = args.config
    if config is None:
        config = get_default_config()
    root, closer = open_root(config)

    # EXEC COMMANDS
    cmd = args.command.strip().lower()
    try:
        if cmd == 'list':
            do_list(args, root)
        elif cmd == 'add':
            do_add(args, root)
        elif cmd == 'remove':
            do_remove(args, root)
        elif cmd == 'clear-all':
            do_clearall(args, root)
        elif cmd == 'clear-date':
            do_cleardate(args, root)
    except Exception as ex:
        if args.verbose:
            print ex
        else:
            print "Aborting due to exception"
        transaction.abort()
        sys.exit(0)

    # COMMIT/ABORT
    if args.dryrun:
        if args.verbose:
            print "Dry-run, aborting commit to database."
        transaction.abort()
    else:
        if args.verbose:
            print "Committing to database."
        transaction.commit()


if __name__ == '__main__':
    main()
