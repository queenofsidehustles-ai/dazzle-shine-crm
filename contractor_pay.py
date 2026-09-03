"""What each cleaner has earned, what they have been paid, and what is owed.

The CRM already knew what a cleaner earns on a job — `Booking.pay_for(staff)` is
the single answer the offer, My Day, payroll and the payout all read, so they
cannot quote different numbers. What it did not do was write that down anywhere
until the owner pressed Pay on the payroll screen. Until she did, a completed
job left no trace of the cost: her P&L counted the customer's $290 as revenue
and nothing at all as labor, so every job looked far more profitable than it
was, and there was no screen anywhere that answered "what do I owe Genesis?"

So a completed job now queues the payment instead of waiting to be remembered.
The row exists the moment the work is done, carrying the right amount, marked
`pending` — and `pending` is deliberate: `finance.contractor_pay_between()`
counts only `status == 'paid'`, so a queued payment never claims money left the
bank that has not. It is a to-do list with the arithmetic already done. When she
actually pays it, the same row becomes `paid`, on the date the money moved, and
that is the day it reaches the P&L.

One row per (staff, booking), enforced on the way in, so a job re-saved as
completed a second time cannot queue a second payment for the same work.
"""
from datetime import datetime

from extensions import db
from models import Booking, ContractorPayment, Staff


def staff_for_booking(booking):
    """Everyone owed money for this job, with what each of them earned.

    Crew jobs pay per person at the split the owner set; a solo job pays the one
    assigned cleaner. Returns [(staff, amount)], skipping anyone who works out
    at nothing — an unpriced job should queue no payment rather than a $0 one.
    """
    out = []
    if booking.crew:
        for row in booking.crew:
            if row.staff:
                out.append((row.staff, round(row.pay_amount or 0, 2)))
    else:
        s = match_staff(booking.assigned_cleaner)
        if s:
            out.append((s, round(booking.pay_for(s) or 0, 2)))
    return [(s, amt) for s, amt in out if amt > 0]


def match_staff(name):
    """The team member a job's `assigned_cleaner` string refers to.

    Deliberately does NOT filter on is_active. Payroll built its lookup from
    active staff only and silently skipped anything it could not match, so
    deactivating a cleaner who was still owed for last week's jobs erased those
    jobs from the only screen that could have paid her. Somebody leaving is not
    a reason to stop owing them money.
    """
    name = (name or '').strip()
    if not name:
        return None
    return Staff.query.filter(db.func.lower(Staff.name) == name.lower()).first()


def existing_payment(staff_id, booking_id):
    """Any payment already recorded for this person on this job, paid or not."""
    return ContractorPayment.query.filter_by(
        staff_id=staff_id, booking_id=booking_id).first()


def queue_for_booking(booking):
    """Record what is owed for a completed job. Returns the rows created.

    Called when a job becomes completed. Never raises and never sends anything:
    marking a job done must not fail because of bookkeeping, and nobody is told
    about a payment until it is actually issued.
    """
    created = []
    try:
        for staff, amount in staff_for_booking(booking):
            if existing_payment(staff.id, booking.id):
                continue                  # already queued, or already paid
            pay = ContractorPayment(
                staff_id=staff.id, booking_id=booking.id, amount=amount,
                tip_amount=0, method='', status='pending',
                note=f'{staff.name} — {booking.name or "job"} '
                     f'{booking.preferred_date or ""}'.strip(),
            )
            db.session.add(pay)
            created.append(pay)
        if created:
            db.session.commit()
    except Exception:
        db.session.rollback()
        return []
    return created


def summary_for(staff):
    """Earned, paid and still owed for one cleaner — all time.

    'Earned' is every job they have actually worked, solo and crew, which is a
    different question from what has been written down: a job completed before
    queuing existed has no payment row at all. Owed is therefore worked out from
    the work, not from the rows, or the backlog would be invisible.
    """
    jobs = jobs_worked(staff)
    earned = round(sum(j.pay_for(staff) or 0 for j in jobs), 2)
    paid = round(float(db.session.query(db.func.sum(ContractorPayment.amount))
                       .filter(ContractorPayment.staff_id == staff.id,
                               ContractorPayment.status == 'paid')
                       .scalar() or 0), 2)
    return {'jobs': len(jobs), 'earned': earned, 'paid': paid,
            'owed': round(max(0.0, earned - paid), 2)}


def jobs_worked(staff, limit=None):
    """Completed jobs this cleaner actually worked — solo AND crew.

    The team page only ever asked for solo jobs (`assigned_cleaner = name`), so
    every crew job a cleaner worked was missing from their own page. This is the
    query the printable pay statement already used; both now read the same one.
    """
    from models import BookingCrew
    q = (Booking.query
         .outerjoin(BookingCrew, BookingCrew.booking_id == Booking.id)
         .filter(db.or_(db.func.lower(Booking.assigned_cleaner) == (staff.name or '').lower(),
                        BookingCrew.staff_id == staff.id),
                 Booking.status == 'completed')
         .distinct()
         .order_by(Booking.preferred_date.desc()))
    jobs = q.all()
    # A crew job they are not actually on — they are only the stale lead name.
    jobs = [j for j in jobs if not (j.crew and not j.crew_row_for(staff))]
    return jobs[:limit] if limit else jobs


def notify_paid(staff, amount, method, when=None, tip=0.0, job_label=''):
    """Tell a cleaner their money has been sent — by email and by text.

    Best-effort by design and never raises: the money has already moved by the
    time this runs, and a failed text must not roll that back or look like a
    failed payment. Returns (emailed, texted) so the caller can say what
    actually reached them rather than claiming both.
    """
    import branding
    from notifications import send_email, send_sms

    biz = branding.biz_name()
    total = round((amount or 0) + (tip or 0), 2)
    how = {'stripe': 'Stripe direct deposit', 'cash': 'cash', 'zelle': 'Zelle',
           'venmo': 'Venmo', 'check': 'check'}.get((method or '').lower(),
                                                   (method or 'bank transfer').title())
    when = when or datetime.utcnow()
    on_day = when.strftime('%b %-d, %Y')
    for_job = f' for {job_label}' if job_label else ''
    tip_line = f' (${amount:.2f} pay + ${tip:.2f} tip)' if tip else ''
    first = (staff.name or 'there').split()[0]

    emailed = texted = False
    if staff.email:
        try:
            emailed, _ = send_email(
                to_email=staff.email, to_name=staff.name,
                subject=f'Payment sent — ${total:.2f} from {biz}',
                html=f"""
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Hi {first} — your payment is on its way 💸</h2>
  <p>We've issued <strong>${total:.2f}</strong>{for_job} by <strong>{how}</strong> on {on_day}.{tip_line}</p>
  <table style="width:100%;border-collapse:collapse;margin:18px 0;font-size:14px">
    <tr><td style="padding:6px 0;color:#6b6580">Amount</td>
        <td style="padding:6px 0;text-align:right"><strong>${total:.2f}</strong></td></tr>
    <tr><td style="padding:6px 0;color:#6b6580">Method</td>
        <td style="padding:6px 0;text-align:right">{how}</td></tr>
    <tr><td style="padding:6px 0;color:#6b6580">Issued</td>
        <td style="padding:6px 0;text-align:right">{on_day}</td></tr>
  </table>
  <p style="color:#6b6580;font-size:0.9rem">Direct deposits can take 1–2 business days to land.
     If anything looks wrong, just reply to this email.</p>
  <p style="color:#9a95ad;font-size:13px;margin-top:20px">{biz}</p>
</div>""")
        except Exception:
            emailed = False
    if staff.phone:
        try:
            # Transactional, not marketing: this is somebody's wages, so it goes
            # through send_sms rather than send_marketing_sms and carries no
            # opt-out — a cleaner who stopped marketing still needs paying.
            texted, _ = send_sms(
                staff.phone,
                f"Hi {first}! {biz} has issued ${total:.2f}{for_job} by {how} on {on_day}. "
                f"Direct deposits can take 1-2 business days to arrive.")
        except Exception:
            texted = False
    return bool(emailed), bool(texted)
