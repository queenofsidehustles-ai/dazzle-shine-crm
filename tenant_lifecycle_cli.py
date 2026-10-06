"""Safe operator commands for registered-tenant closure and retention purge.

This intentionally lives outside provisioning.py so the provisioning cleanup
primitive remains narrowly scoped and the operator lifecycle can be reviewed,
tested and evolved independently.
"""
import argparse
import sys

import control_plane
import provisioning
import tenant_data_lifecycle as lifecycle


def main(argv=None):
    parser = argparse.ArgumentParser(description='Manage registered tenant lifecycle safely.')
    sub = parser.add_subparsers(dest='action', required=True)

    close = sub.add_parser('close', help='revoke access and start the 30-day retention period')
    close.add_argument('slug')
    close.add_argument('--yes', action='store_true')

    purge = sub.add_parser('purge', help='purge a closed tenant only after retention eligibility')
    purge.add_argument('slug')
    purge.add_argument('--yes', action='store_true')

    args = parser.parse_args(argv)
    engine = provisioning._engine()
    org = control_plane.find(engine, args.slug)
    if not org:
        print(f'  No company called {args.slug!r}.')
        return 1

    if args.action == 'close':
        print(f'\n  Close {org["name"]}: access ends immediately; data remains recoverable for 30 days.\n')
        if not args.yes and input(f'  Type {args.slug} to confirm closure: ').strip() != args.slug:
            print('  Nothing was changed.\n')
            return 1
        lifecycle.close_tenant(engine, args.slug)
        print(f'  {org["name"]} closed; retention period started.\n')
        return 0

    if not lifecycle.purge_eligible(engine, args.slug):
        print('  Purge refused: the 30-day retention requirement is not satisfied.\n')
        return 1
    print(f'\n  Permanently purge retained tenant data for {org["name"]}. This is irreversible.\n')
    if not args.yes and input(f'  Type {args.slug} to confirm permanent purge: ').strip() != args.slug:
        print('  Nothing was changed.\n')
        return 1
    lifecycle.purge_tenant(engine, args.slug)
    print(f'  {org["name"]} purged after retention eligibility was verified.\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
