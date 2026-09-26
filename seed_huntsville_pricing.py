"""Load Huntsville's price book into the Huntsville tenant.

    TENANT_SLUG=huntsville python3 seed_huntsville_pricing.py          # dry run
    TENANT_SLUG=huntsville python3 seed_huntsville_pricing.py --write

Huntsville is not a discount market — Redstone Arsenal, Cummings Research Park
and the Toyota-Mazda plant keep household income high even though cost of
living trails Orlando. So these are not Orlando's prices marked down. They are
anchored to the market: Valley Clean Team, the closest comparable local
operator, publishes floors of $200 standard / $276 deep / $351 move-out, and
this book sits $11-15 under each of those at the entry size.

The slope from that entry is deliberately flatter than Orlando's. North Alabama
homes are bigger and cheaper per square foot, so Orlando's curve applied to a
higher entry price ran a five-bedroom move-out past $900 — far outside anything
this market pays. Flattened, every 3bd/2ba price lands inside the researched
local bands (standard $150-275, deep $250-400, move-out $300-500) while the
advertised entry price still beats the nearest competitor.

Contractor pay at the 50% split runs $31-62/hour, which is the number that
actually matters: hiring is the critical path in a new market, not price.
"""
import os
import sys

# (beds, baths) -> standard price. Deep and move-out derive from the
# multipliers below, so only this table and those two numbers are tuned.
PRICE_MATRIX = {
    (1, 1): 185,   # entry — Valley Clean Team's floor is $200
    (1, 2): 200,
    (2, 1): 210,
    (2, 2): 230,
    (3, 2): 255,   # the size most customers quote
    (3, 3): 285,
    (4, 2): 305,
    (4, 3): 335,
    (5, 3): 375,
    (5, 4): 410,
}

# Orlando runs 1.6x / 1.9x. This market runs flatter — Valley prices deep at
# 1.38x and move-out at 1.76x, and pricing off Orlando's steeper pair would put
# every deep clean above the local band.
MULTIPLIERS = {
    'deep': 1.43,      # $265 at entry vs Valley's $276
    'moveout': 1.83,   # $339 at entry vs Valley's $351
}

# Unchanged from Orlando: these are policy, not market rate.
UNCHANGED = ('standard', 'postcon_clean', 'postcon_final', 'postcon_full')


def main():
    write = '--write' in sys.argv
    slug = os.environ.get('TENANT_SLUG', '')
    if not slug:
        sys.exit('Set TENANT_SLUG (e.g. TENANT_SLUG=huntsville). Refusing to guess '
                 'which company these prices belong to.')

    from app import create_app
    import tenancy
    from models import db, PricingSetting

    app = create_app()

    schema = tenancy.schema_for(slug)
    if schema == tenancy.PUBLIC or not schema.startswith(tenancy.SCHEMA_PREFIX):
        sys.exit(f'{slug!r} resolves to the PUBLIC schema, which is the host '
                 'instance rather than a tenant. These prices must never land '
                 'there.')

    with app.app_context(), tenancy.use_tenant(schema):
        # SQLite has no schemas, so use_tenant() above is silently a no-op there
        # and every write lands in the one and only pricing table. Against a
        # local database that is merely useless; against anything shared it is
        # Orlando's price book overwritten with Huntsville's. Refuse outright.
        if db.engine.dialect.name != 'postgresql':
            sys.exit(f'Connected to {db.engine.dialect.name}, not PostgreSQL. Tenant '
                     'schemas do not exist there, so this would write Huntsville '
                     'prices into whatever single price book it found. Set '
                     'DATABASE_URL to the Railway Postgres and re-run.')
        print(f'tenant: {slug}   schema: {schema}')

        for (beds, baths), price in sorted(PRICE_MATRIX.items()):
            key = f'std_price_{beds}_{baths}'
            print(f'  {key:<18} {PricingSetting.get(key)!s:>8} -> {price}')
            if write:
                PricingSetting.set(key, price)

        for service, mult in MULTIPLIERS.items():
            key = f'{service}_multiplier'
            print(f'  {key:<18} {PricingSetting.get(key)!s:>8} -> {mult}')
            if write:
                PricingSetting.set(key, mult)

        print(f'  (unchanged: {", ".join(UNCHANGED)})')

        if write:
            db.session.commit()
            print('\nwritten.')
        else:
            print('\ndry run — nothing written. Re-run with --write.')


if __name__ == '__main__':
    main()
