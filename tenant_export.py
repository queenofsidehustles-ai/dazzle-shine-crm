"""A copy of one company's business data, made by staff on the owner's request.

The product already lets an owner download their own customers, jobs and workers
(settings.export). That stops working the moment a company is closed: access is
revoked immediately, and the owner is exactly who then needs their data. The
policy (AKYE_DATA_LIFECYCLE_POLICY.md) says an authorized owner may request an
export before purge, so somebody at Akye has to be able to make one.

## Explicit columns, never a blind dump

Each file lists the columns it carries. It does not `SELECT *` and filter, so a
column added to a table next year is not exported until someone decides it
should be. What is deliberately not here: logins and password hashes, two-factor
secrets, card details, payment-provider ids, portal and agreement tokens,
private documents (W-9s, IDs), message history, integration keys and anything
belonging to another company. The README in the zip says so.

## One company, by construction

The schema is derived from a validated slug, never accepted from input, and
every query runs inside that company's own schema. A closed company can be read
(its data is retained on purpose); a purged one cannot, because there is nothing
left.

## Spreadsheet formulas

A customer's name or note that starts with = + - or @ would run as a formula
when the file is opened in a spreadsheet. Text cells like that are prefixed with
an apostrophe. Numbers and dates are never touched.
"""
import csv
import io
import zipfile
from datetime import datetime

import tenancy


class ExportError(RuntimeError):
    pass


_FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


def safe(value):
    """A cell as text, with spreadsheet formulas defused. Non-text passes through."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _iso(value):
    return value.isoformat() if value else ''


def _money(value):
    return f'{value:.2f}' if value is not None else ''


def _text(value):
    return safe((value or '').replace('\n', ' ') if isinstance(value, str) else (value or ''))


def _customers():
    from models import Client
    header = ['ID', 'Name', 'Email', 'Phone', 'Address', 'City', 'Zip',
              'Total Bookings', 'Autopay', 'Customer Since', 'Notes']
    rows = [[c.id, safe(c.name), safe(c.email or ''), safe(c.phone or ''),
             safe(c.address or ''), safe(c.city or ''), safe(c.zip_code or ''),
             len(c.bookings), c.autopay, _iso(c.created_at), _text(c.notes)]
            for c in Client.query.order_by(Client.created_at.asc()).all()]
    return header, rows


def _jobs():
    from models import Booking
    header = ['ID', 'Client Name', 'Email', 'Phone', 'Address', 'City', 'Service',
              'Bedrooms', 'Bathrooms', 'Date', 'Time', 'Frequency', 'Status',
              'Price', 'Discount', 'Assigned To', 'Created']
    rows = [[b.id, safe(b.name or ''), safe(b.email or ''), safe(b.phone or ''),
             safe(b.address or ''), safe(b.city or ''), b.service_type,
             b.bedrooms or '', b.bathrooms or '', b.preferred_date or '',
             b.preferred_time or '', b.frequency, b.status, _money(b.price),
             _money(b.discount_amount or 0), safe(b.assigned_cleaner or ''),
             _iso(b.created_at)]
            for b in Booking.query.order_by(Booking.created_at.asc()).all()]
    return header, rows


def _workers():
    from models import Staff
    header = ['ID', 'Name', 'Email', 'Phone', 'Active', 'Pay Type', 'Pay Rate',
              'Experience Level']
    rows = [[s.id, safe(s.name), safe(s.email or ''), safe(s.phone or ''),
             s.is_active, s.pay_type, s.pay_rate, s.experience_level or '']
            for s in Staff.query.order_by(Staff.name.asc()).all()]
    return header, rows


def _pay():
    """What the business paid its workers. Needed at tax time, which is exactly
    when a closed business comes asking."""
    from models import ContractorPayment, Staff
    names = {s.id: s.name for s in Staff.query.all()}
    header = ['ID', 'Worker', 'Job ID', 'Amount', 'Tip', 'Method', 'Status', 'Note', 'Date']
    rows = [[p.id, safe(names.get(p.staff_id, '')), p.booking_id or '',
             _money(p.amount), _money(p.tip_amount or 0), p.method or '',
             p.status or '', _text(p.note), _iso(p.created_at)]
            for p in ContractorPayment.query.order_by(ContractorPayment.created_at.asc()).all()]
    return header, rows


def _expenses():
    from models import Expense
    header = ['ID', 'Date', 'Category', 'Amount', 'Vendor', 'Note', 'Method',
              'Miles', 'Rate per Mile', 'Created']
    rows = [[e.id, e.date or '', e.category or '', _money(e.amount),
             safe(e.vendor or ''), _text(e.note), e.method or '',
             e.miles or '', e.rate_per_mile or '', _iso(e.created_at)]
            for e in Expense.query.order_by(Expense.created_at.asc()).all()]
    return header, rows


DATASETS = [
    ('customers.csv', 'Customers', _customers),
    ('jobs.csv', 'Jobs', _jobs),
    ('workers.csv', 'Workers', _workers),
    ('worker-payments.csv', 'Payments to workers', _pay),
    ('expenses.csv', 'Expenses', _expenses),
]

LEFT_OUT = [
    'Sign-in accounts, passwords and two-factor secrets',
    'Card numbers and card details, and payment-provider ids',
    'Private documents such as W-9s and ID uploads',
    'Message history, and the keys for connected services',
    "Anything that belongs to another company",
]


def _readme(org, counts, by, now):
    lines = [
        f'Export of {org["name"]} ({org["slug"]})',
        f'Made {now:%Y-%m-%d %H:%M} UTC by {by or "Akye staff"}.',
        '',
        'What is in this file:',
    ]
    for filename, label, _fn in DATASETS:
        lines.append(f'  {filename:<22} {label}: {counts.get(filename, 0):,} rows')
    lines += ['', 'What is deliberately not in it:']
    lines += [f'  - {item}' for item in LEFT_OUT]
    lines += ['',
              'Text that begins with = + - or @ has an apostrophe added in front, so a',
              'spreadsheet shows it as written instead of running it as a formula.',
              '',
              'This file contains personal information about your customers and workers.',
              'Keep it somewhere private and delete it when you no longer need it.']
    return '\n'.join(lines) + '\n'


def build(engine, slug, *, by=None, now=None):
    """(zip_bytes, counts). Raises ExportError with a sentence staff can act on."""
    import console_data
    import tenant_data_lifecycle as lifecycle
    from extensions import db

    now = now or datetime.utcnow()
    try:
        org = lifecycle.lifecycle_state(engine, slug)
    except lifecycle.LifecycleError as exc:
        raise ExportError(str(exc)) from exc
    if not org:
        raise ExportError('No such company.')
    if org.get('purged_at'):
        raise ExportError('This company has been purged. There is nothing left to export.')
    if not console_data.schema_ready(slug):
        raise ExportError('This company has no data of its own to export.')

    counts = {}
    files = {}
    db.session.remove()
    try:
        with tenancy.use_tenant(slug):
            for filename, _label, fn in DATASETS:
                header, rows = fn()
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(header)
                w.writerows(rows)
                files[filename] = buf.getvalue()
                counts[filename] = len(rows)
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f'The export could not be read ({type(exc).__name__}). '
                          f'Nothing was sent.') from exc
    finally:
        db.session.remove()

    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.txt', _readme(org, counts, by, now))
        for filename, content in files.items():
            z.writestr(filename, '﻿' + content)     # BOM: Excel reads UTF-8 names right
    return out.getvalue(), counts
