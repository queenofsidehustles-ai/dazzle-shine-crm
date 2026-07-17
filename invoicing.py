"""Real invoicing — turns a booking into a numbered, itemized, branded invoice.

Reuses the booking's existing pay flow for payment; this layer adds a proper
invoice number, issue/due dates, status, and line items so customers receive a
real 'Invoice #INV-1042', not just a pay link.
"""
from datetime import datetime, date, timedelta

NET_DAYS = 14  # payment due this many days after issuing


def next_invoice_number():
    """Sequential invoice number, e.g. INV-1042 (counter in BusinessSetting)."""
    from models import BusinessSetting
    from extensions import db
    cur = int(float(BusinessSetting.get('invoice_counter') or 1041))
    cur += 1
    BusinessSetting.set('invoice_counter', cur)
    db.session.commit()
    return f'INV-{cur}'


def issue(booking):
    """Assign an invoice number + dates if this booking hasn't been invoiced yet."""
    from extensions import db
    if not booking.invoice_number:
        booking.invoice_number = next_invoice_number()
    if not booking.invoice_issued_at:
        booking.invoice_issued_at = datetime.utcnow()
    if not booking.invoice_due_date:
        booking.invoice_due_date = (date.today() + timedelta(days=NET_DAYS)).isoformat()
    db.session.commit()
    return booking


def status(booking):
    if booking.paid_at:
        return 'paid'
    if not booking.invoice_issued_at:
        return 'draft'
    if booking.invoice_due_date and booking.invoice_due_date < date.today().isoformat():
        return 'overdue'
    return 'sent'


STATUS_LABELS = {'paid': 'Paid', 'overdue': 'Overdue', 'sent': 'Sent', 'draft': 'Draft'}


def line_items(booking):
    """Build itemized rows for the invoice from the booking's fields."""
    from pricing import DEPOSIT_AMOUNT
    rows = []
    svc = getattr(booking, 'service_label', None) or (booking.service_type or 'Cleaning service')
    size = []
    if booking.bedrooms:
        size.append(f'{booking.bedrooms} bd')
    if booking.bathrooms:
        size.append(f'{booking.bathrooms} ba')
    desc = svc + (f' ({", ".join(size)})' if size else '')
    rows.append((desc, booking.price or 0))
    if booking.extras:
        rows.append((f'Add-ons: {booking.extras}', None))
    if booking.discount_amount:
        rows.append((f'Discount{(" (" + booking.discount_code + ")") if booking.discount_code else ""}',
                     -abs(booking.discount_amount)))
    if booking.deposit_paid:
        rows.append(('Deposit already paid', -abs(DEPOSIT_AMOUNT)))
    return rows
