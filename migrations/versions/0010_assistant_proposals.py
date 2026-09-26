"""What Nana offered to do, and whether a person said yes.

Until now the one thing she could act on came back to the browser as a job id,
and the browser posted that id to a confirm route. That is fine while the only
action is marking your own job finished -- the worst a tampered id does is
finish a different job of your own, which is visible and undoable.

It stops being fine the moment she can send. "The page posts what to do" means
what runs is only probably what was read and approved, and for anything that
leaves the building, probably is not a standard.

So a proposal is written down before it is offered, and the page gets nothing
but a token. What executes is read back from here, so it is the same thing that
was on screen by construction rather than by trust.

The row stays afterwards on purpose. Once software can act on a business's
behalf, "who approved this, and what did it say at the time" is the first
question anybody asks, and it cannot be answered later by a system that only
kept the outcome.
"""
import sqlalchemy as sa
from alembic import op

revision = '0010_assistant_proposals'
down_revision = '0009_merge_hold_and_debris'
branch_labels = None
depends_on = None


def _current_schema():
    """The schema this migration is running in, or None on SQLite.

    Same shape as 0004 and 0005: SQLite has no schemas and no current_schema()
    function, and asking it raises rather than returning nothing.
    """
    import sqlalchemy as _sa
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(_sa.text('SELECT current_schema()')).scalar()


def _has_table(name):
    from sqlalchemy import inspect as sa_inspect
    return name in sa_inspect(op.get_bind()).get_table_names(
        schema=_current_schema())


def upgrade():
    # A database built straight from the models and then adopted at baseline
    # already has this table. Creating it again is the failure that stops such
    # an install from ever migrating forward.
    if _has_table('assistant_proposal'):
        return
    op.create_table(
        'assistant_proposal',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('summary', sa.Text(), nullable=False, server_default=''),
        sa.Column('label', sa.String(120), nullable=False, server_default='Confirm'),
        sa.Column('reversible', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column('asked_by', sa.String(120)),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('used_at', sa.DateTime()),
        sa.Column('outcome', sa.Text()),
    )
    # Unique, because a token is how one particular offer is found and spent.
    op.create_index('ix_assistant_proposal_token', 'assistant_proposal',
                    ['token'], unique=True)


def downgrade():
    if not _has_table('assistant_proposal'):
        return
    op.drop_index('ix_assistant_proposal_token', table_name='assistant_proposal')
    op.drop_table('assistant_proposal')
