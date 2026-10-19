"""Placeholder for databases that recorded the photo-wording migration as 0021.

The wording change shipped on `main` as 0021 and on `akye-stable` as 0033, two
names for one idempotent text replace. It now has a single real home,
0033_photo_optional_wording, which is the same file on both branches. This
no-op keeps the 0021 id resolvable for any database already stamped with it,
and sits after 0033 so a fresh database runs the replace exactly once.
"""
revision = '0021_photo_optional_wording'
down_revision = '0033_photo_optional_wording'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
