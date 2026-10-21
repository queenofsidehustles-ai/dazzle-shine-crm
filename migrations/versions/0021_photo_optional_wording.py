"""An id main gave the photo-wording change, kept so a database stamped with it
still resolves here.

The wording change shipped on `main` as 0021_photo_optional_wording and on
`akye-stable` as 0033_photo_optional_wording: two names for one idempotent text
replace. main's own instance may be stamped 0021_photo_optional_wording, which
akye-stable's history did not contain, so `upgrade` there would stop with "Can't
locate revision". It sits here, between 0020 and 0021_quote_prospect, as a
no-op: a database stamped with it then runs 0021_quote_prospect through 0033 as
it should (0033 replaces the wording again, harmlessly), and a database already
past 0021_quote_prospect counts it as applied and runs nothing new. The head is
unchanged.
"""
revision = '0021_photo_optional_wording'
down_revision = '0020_booking_cc'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
