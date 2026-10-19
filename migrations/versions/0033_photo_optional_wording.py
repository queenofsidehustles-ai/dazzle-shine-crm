"""Photos are optional, so no checklist item may ask a cleaner to vouch for them.

Reword the two photo-attesting items in every company's saved checklist
templates and in jobs not yet closed out. Items are matched by text and
replaced in place, so a job's ticked items (stored by position) stay ticked.
"""
from alembic import op
import sqlalchemy as sa

revision = '0033_photo_optional_wording'
down_revision = '0020_booking_cc'
branch_labels = None
depends_on = None

SWAPS = (('— document condition with photos', '— check and note condition'),
         ('Take photos when complete', 'Final look-over before leaving'))


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table, where in (('checklist_template', ''),
                         ('job_checklist', ' AND photos_submitted_at IS NULL')):
        if table not in tables:
            continue
        for old, new in SWAPS:
            bind.execute(
                sa.text(f"UPDATE {table} SET items = REPLACE(items, :old, :new) "
                        f"WHERE items LIKE :like{where}"),
                {'old': old, 'new': new, 'like': f'%{old}%'})


def downgrade():
    pass   # wording only; nothing worth putting back
