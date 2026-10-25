"""Call recordings wait for a yes, and are deleted on a schedule.

Recording used to start the moment the other person answered, with a notice
that the call "may be recorded". That is not consent in every state, so it now
starts only when they press 1, and each call keeps what they said. Recordings
are deleted from Twilio after voice.RECORDING_KEEP_DAYS, or sooner by the
owner, and the call keeps when that happened.

Two nullable columns on call_log and nothing else.
"""
from alembic import op
import sqlalchemy as sa

revision = '0039_call_recording_consent'
down_revision = '0038_call_log'
branch_labels = None
depends_on = None


def _schema():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return None
    return bind.execute(sa.text('SELECT current_schema()')).scalar()


def _columns():
    from sqlalchemy import inspect as sa_inspect
    return {c['name'] for c in sa_inspect(op.get_bind()).get_columns('call_log', schema=_schema())}


def upgrade():
    have = _columns()
    if 'recording_consent' not in have:
        op.add_column('call_log', sa.Column('recording_consent', sa.String(10), nullable=True))
    if 'recording_deleted_at' not in have:
        op.add_column('call_log', sa.Column('recording_deleted_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('call_log', 'recording_deleted_at')
    op.drop_column('call_log', 'recording_consent')
