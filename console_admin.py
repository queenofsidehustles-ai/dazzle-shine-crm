"""Create the first console account, from a terminal.

Only the first one needs this. After that people are added from the People
page by somebody who is already an owner -- which is the point of the console
existing at all, since the whole problem was that everything cross-company
required a terminal and a production database URL.

    python3 console_admin.py add you@example.com "Your Name" --owner
    python3 console_admin.py password you@example.com
    python3 console_admin.py list

The password is asked for, never passed as an argument: a password on the
command line is in the shell history and in the process list.
"""
import argparse
import getpass
import sys

import control_plane
import provisioning


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['add', 'password', 'list', 'off'])
    ap.add_argument('email', nargs='?')
    ap.add_argument('name', nargs='?', default='')
    ap.add_argument('--owner', action='store_true',
                    help='can add and remove other people')
    args = ap.parse_args()

    engine = provisioning._engine()
    control_plane.ensure_table(engine)

    if args.action == 'list':
        rows = control_plane.console_users_all(engine)
        if not rows:
            print('\n  Nobody can sign into the console yet.\n')
            return 0
        print(f'\n  {"email":<34} {"role":<7} {"active":<7} last in')
        print('  ' + '-' * 70)
        for r in rows:
            last = r['last_login_at'].strftime('%d %b %H:%M') if r['last_login_at'] else 'never'
            print(f'  {r["email"]:<34} {r["role"]:<7} '
                  f'{"yes" if r["active"] else "no":<7} {last}')
        print()
        return 0

    if not args.email:
        print('Which email?')
        return 1

    if args.action == 'off':
        control_plane.set_console_active(engine, args.email, False)
        print(f'\n  {args.email} can no longer sign in.\n')
        return 0

    pw = getpass.getpass('Password (12 characters or more): ')
    if len(pw) < 12:
        print('  Too short.')
        return 1
    if pw != getpass.getpass('Again: '):
        print('  Those do not match.')
        return 1

    if args.action == 'add':
        if control_plane.console_user(engine, args.email):
            print(f'  {args.email} is already on the list. '
                  f'Use "password" to change it.')
            return 1
        control_plane.add_console_user(
            engine, args.email, args.name, pw,
            role='owner' if args.owner else 'staff')
        print(f'\n  {args.email} can sign in at /console.\n')
    else:
        control_plane.set_console_password(engine, args.email, pw)
        print(f'\n  Password changed for {args.email}.\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
