"""The owner, as their own first cleaner.

A new owner often has no cleaners yet, because they are the cleaner. A job can
only be assigned to a Staff row, so "add a cleaner" used to be a step they had
to invent somebody for, or add themselves by hand, before the first job could
be scheduled. Signup now creates that row.

What makes it different from every other Staff row:

  * `is_owner` is true, so payroll, the 1099 list and the contractor reminders
    skip it. Nobody pays the owner through the CRM for their own work.
  * pay_rate is 0, and no agreement or payout paperwork is asked of them.
  * It counts as one of the plan's field workers, which is what the Solo plan
    always meant by "them, plus helpers" (entitlements.py).

`hired_team_count` is the number of people who are not the owner: what "has a
team" means for setup and activation now that every new company starts with one
cleaner.
"""
from extensions import db


def ensure(owner, email=None):
    """Create the owner's cleaner row if the company has none. Returns it.

    Idempotent, and leaves a row somebody already made alone: it looks for an
    owner row, then for one linked to this login, before adding another."""
    from models import Staff
    existing = (Staff.query.filter_by(is_owner=True).first()
                or Staff.query.filter_by(user_id=owner.id).first())
    if existing:
        return existing
    row = Staff(name=owner.name, email=(email or '').strip().lower() or None,
                user_id=owner.id, is_owner=True, is_active=True,
                pay_type='percent', pay_rate=0)
    db.session.add(row)
    db.session.commit()
    return row


def hired_team_count():
    """Active team members other than the owner."""
    from models import Staff
    return (Staff.query.filter(Staff.is_active.is_(True),
                               Staff.is_owner.isnot(True)).count())
