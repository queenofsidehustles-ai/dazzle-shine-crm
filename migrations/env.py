"""Alembic's entry point, wired to this application's models.

Deliberately does not import create_app(): booting the app runs create_all(),
the old _migrate_db(), and a dozen seed functions, and a migration tool that
alters the database on the way to deciding what to alter is not a tool anybody
should trust. Only the metadata is needed, and models.py can be imported on its
own.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url():
    """The same URL create_app() would use, normalised the same way."""
    import backup                      # normalise() lives there already
    return backup.normalise(os.environ.get('DATABASE_URL', ''))


import extensions                       # noqa: E402  (needs ROOT on the path)
import models                           # noqa: E402,F401  (registers every table)
target_metadata = extensions.db.metadata


def run_migrations_offline():
    """Print the SQL instead of running it. This is the dry run."""
    context.configure(
        url=database_url(), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={'paramstyle': 'named'},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section, {})
    section['sqlalchemy.url'] = database_url()
    connectable = engine_from_config(section, prefix='sqlalchemy.',
                                     poolclass=pool.NullPool)

    # Set by provisioning.py when building or upgrading one company's schema.
    # Absent for the ordinary case: the single-business instance, whose tables
    # are in public and always have been.
    schema = config.attributes.get('tenant_schema')

    with connectable.connect() as connection:
        if schema:
            # Point every statement in the migration at this company, and give
            # the company its own version table inside its own schema. Sharing
            # one version row across all companies would mean the first upgrade
            # marked every company as done, and the rest would never be built.
            from sqlalchemy import text
            connection.execute(text(f'SET search_path TO "{schema}", public'))
            connection.commit()

        context.configure(
            connection=connection, target_metadata=target_metadata,
            compare_type=True,
            version_table_schema=schema or None,
            include_schemas=False,
            # Every migration runs inside one transaction, so a failure halfway
            # through leaves the database as it was rather than half-altered.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
