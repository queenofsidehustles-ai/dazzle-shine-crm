"""What was sent, to whom, and what the customer agreed to -- kept for good.

A quote's link showed the quote row as it stood, and an acceptance left a
status and a timestamp: nothing said which terms were accepted, by whom, or
whether the email ever left. Three tables, each written once:

  commercial_quote_revision  the terms frozen at sending -- canonical JSON and
                             its SHA-256. The customer's link is bound to one.
  commercial_quote_delivery  every attempt to send one: recipient, provider,
                             the provider's message id, accepted or failed.
  commercial_quote_response  the answer: revision, hash, typed name and title,
                             time, IP, browser, and the account it linked to.

Revisions and responses refuse UPDATE in the database itself (a trigger), not
only in the app, and a quote can only be bound to a revision of its own (a
constraint trigger, checked at commit). DELETE is left to foreign keys -- a revision someone answered
cannot go, a draft's unsent attempts go with the draft -- because a backup
restore empties every table before refilling it.

On commercial_quote: issued_revision_id (the link's revision), valid_days and
expires_at (an offer closes), account_id (the account it is for, linked by key
rather than by matching names). Quotes already on file read NULL for all but
valid_days; those sent before today are frozen the first time they are
answered (origin 'backfill').
"""
from alembic import op
import sqlalchemy as sa

revision = '0029_quote_evidence'
down_revision = '0028_quote_withdrawn'
branch_labels = None
depends_on = None

FROZEN = ('commercial_quote_revision', 'commercial_quote_response')


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    """In the schema being migrated -- see 0019 for why."""
    from sqlalchemy import inspect as sa_inspect
    return name in set(sa_inspect(op.get_bind()).get_table_names(schema=_schema()))


def _has_column(table, column):
    from sqlalchemy import inspect as sa_inspect
    return column in {c['name']
                      for c in sa_inspect(op.get_bind()).get_columns(table, schema=_schema())}


def upgrade():
    for name, col in (('issued_revision_id', sa.Column('issued_revision_id', sa.Integer(), nullable=True)),
                      ('valid_days', sa.Column('valid_days', sa.Integer(), nullable=True, server_default='30')),
                      ('expires_at', sa.Column('expires_at', sa.DateTime(), nullable=True)),
                      ('account_id', sa.Column('account_id', sa.Integer(), nullable=True))):
        if not _has_column('commercial_quote', name):
            op.add_column('commercial_quote', col)
            if name.endswith('_id'):
                op.create_index(f'ix_commercial_quote_{name}', 'commercial_quote', [name])

    if not _has_table('commercial_quote_revision'):
        op.create_table(
            'commercial_quote_revision',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('quote_id', sa.Integer,
                      sa.ForeignKey('commercial_quote.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('number', sa.Integer, nullable=False),
            sa.Column('terms', sa.Text, nullable=False),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('origin', sa.String(20), nullable=False),
            sa.Column('created_by', sa.String(120)),
            sa.Column('created_at', sa.DateTime, nullable=False),
            sa.UniqueConstraint('quote_id', 'content_hash', name='uq_quote_revision_hash'),
        )
    if not _has_table('commercial_quote_delivery'):
        op.create_table(
            'commercial_quote_delivery',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('quote_id', sa.Integer, nullable=False, index=True),
            sa.Column('revision_id', sa.Integer,
                      sa.ForeignKey('commercial_quote_revision.id', ondelete='CASCADE'),
                      nullable=False, index=True),
            sa.Column('channel', sa.String(10), nullable=False),
            sa.Column('recipient', sa.String(200)),
            sa.Column('provider', sa.String(30)),
            sa.Column('provider_message_id', sa.String(100)),
            sa.Column('status', sa.String(30), nullable=False),
            sa.Column('detail', sa.String(400)),
            sa.Column('sent_by', sa.String(120)),
            sa.Column('created_at', sa.DateTime, nullable=False),
        )
    if not _has_table('commercial_quote_response'):
        op.create_table(
            'commercial_quote_response',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('quote_id', sa.Integer, sa.ForeignKey('commercial_quote.id'),
                      nullable=False, unique=True),
            sa.Column('revision_id', sa.Integer, sa.ForeignKey('commercial_quote_revision.id'),
                      nullable=False, index=True),
            sa.Column('content_hash', sa.String(64), nullable=False),
            sa.Column('decision', sa.String(20), nullable=False),
            sa.Column('signer_name', sa.String(120)),
            sa.Column('signer_title', sa.String(120)),
            sa.Column('signer_email', sa.String(200)),
            sa.Column('ip_address', sa.String(64)),
            sa.Column('user_agent', sa.String(300)),
            sa.Column('account_id', sa.Integer, index=True),
            sa.Column('created_at', sa.DateTime, nullable=False),
        )

    if op.get_bind().dialect.name == 'postgresql':
        # Schema-qualified, so the ownership check reads this company's
        # revisions whatever the search path is when it fires. The same
        # statements re-guard a restored backup (backup._guard_evidence),
        # hence one copy of them, in quote_evidence.
        import quote_evidence
        for statement in quote_evidence.guard_sql(f'"{_schema()}".'):
            op.execute(statement)


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        for table in FROZEN:
            if _has_table(table):
                op.execute(f'DROP TRIGGER IF EXISTS {table}_frozen ON {table}')
        op.execute('DROP TRIGGER IF EXISTS commercial_quote_issued_owned ON commercial_quote')
        op.execute('DROP FUNCTION IF EXISTS quote_evidence_frozen()')
        op.execute('DROP FUNCTION IF EXISTS quote_issued_revision_owned()')
    for table in ('commercial_quote_response', 'commercial_quote_delivery', 'commercial_quote_revision'):
        if _has_table(table):
            op.drop_table(table)
    for name in ('account_id', 'expires_at', 'valid_days', 'issued_revision_id'):
        if _has_column('commercial_quote', name):
            if name.endswith('_id'):
                op.drop_index(f'ix_commercial_quote_{name}', 'commercial_quote')
            op.drop_column('commercial_quote', name)
