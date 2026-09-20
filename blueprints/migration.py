"""The Migration Toolbox — bringing an existing business's team and
customers into Akye without retyping everything by hand.

Two independent CSV imports:

- Team: creates a Staff (contractor) record per row, then emails each
  person a link to set up their own login and finish their own profile --
  the owner never types a password on somebody else's behalf, and the
  resulting login is linked back to their Staff card from the start (see
  Staff.user_id, migration 0014) rather than the two drifting apart the
  way Team Logins created on its own always could.
- Clients: creates a Client record per row directly. An office login is
  already the one doing the importing; there is nobody else to invite.

Calendar/booking-history import is deliberately not here. Mapping another
tool's booking states, pricing and recurrence reliably is a materially
harder problem than a flat contact list, and doing it carelessly risks
corrupting the payroll and P&L numbers those rows would otherwise feed --
it needs its own pass, not to ride along with this one.
"""
import csv
import io
import re
import secrets

from flask import Blueprint, render_template, request, redirect, url_for, flash

from auth import owner_required
from extensions import db
from models import Staff, Client

migration_bp = Blueprint('migration', __name__, url_prefix='/migration')

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _read_csv_rows(file_storage):
    """Parse an uploaded CSV into a list of header-normalised dicts (keys
    lowercased and stripped). Returns (rows, error) -- error is set if the
    file could not be read as a CSV at all, and nothing is imported."""
    try:
        raw = file_storage.read().decode('utf-8-sig')
    except Exception:
        return None, 'Could not read that file as text. Save it as a CSV and try again.'
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return None, 'That file has no header row — the first line should name the columns.'
    reader.fieldnames = [(f or '').strip().lower() for f in reader.fieldnames]
    rows = list(reader)
    if not rows:
        return None, 'That file has a header row but no data rows under it.'
    return rows, None


@migration_bp.route('/')
@owner_required
def index():
    return render_template('admin/migration.html',
                           staff_total=Staff.query.count(),
                           client_total=Client.query.count())


# ── Team import ───────────────────────────────────────────────────────────

@migration_bp.route('/team', methods=['GET', 'POST'])
@owner_required
def team():
    results = None
    if request.method == 'POST':
        f = request.files.get('csv_file')
        if not f or not f.filename:
            flash('Choose a CSV file first.', 'error')
            return redirect(url_for('migration.team'))
        rows, err = _read_csv_rows(f)
        if err:
            flash(err, 'error')
            return redirect(url_for('migration.team'))
        results = _import_team_rows(rows)
    return render_template('admin/migration_team.html', results=results)


def _import_team_rows(rows):
    """Create one Staff record per valid row and email each an invite link.
    Every row gets a verdict -- created, or skipped with a plain-English
    reason -- so nothing is silently dropped from a CSV somebody trusted
    this with."""
    existing = {e.strip().lower() for (e,) in
               db.session.query(Staff.email).all() if e and e.strip()}
    seen_in_file = set()
    created, skipped = [], []

    for i, row in enumerate(rows, start=2):  # row 1 is the header
        name = (row.get('name') or '').strip()
        email = (row.get('email') or '').strip().lower()
        phone = (row.get('phone') or '').strip()
        if not name or not email:
            skipped.append((i, name or email or '(blank row)', 'Missing a name or email.'))
            continue
        if not EMAIL_RE.match(email):
            skipped.append((i, name, f'"{email}" is not a valid email address.'))
            continue
        if email in existing or email in seen_in_file:
            skipped.append((i, name, f'{email} is already a team member (or listed twice in this file).'))
            continue
        seen_in_file.add(email)

        s = Staff(name=name, email=email, phone=phone or None,
                  agreement_token=secrets.token_urlsafe(32))
        db.session.add(s)
        db.session.flush()  # need s.id/token before the email goes out
        ok, detail = send_join_invite(s)
        created.append((i, name, email, ok, detail if not ok else None))

    db.session.commit()
    return {'created': created, 'skipped': skipped}


def send_join_invite(s):
    """Email one Staff record's set-up link. Shared by the bulk importer
    above and contractors.resend_join_invite, so there is one copy of the
    invite email rather than two that can drift apart."""
    import notifications, branding
    if not s.agreement_token:
        s.agreement_token = secrets.token_urlsafe(32)
    biz = branding.biz_name()
    link = url_for('contractors.join_team', token=s.agreement_token, _external=True)
    return notifications.send_email(
        to_email=s.email, to_name=s.name,
        subject=f"You're invited to {biz}",
        html=f'''
<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Welcome to {biz}</h2>
  <p>Hi {s.name.split()[0]} — {biz} has added you to their team. Set up your own
     sign-in to see your schedule and get job offers.</p>
  <p style="margin:22px 0"><a href="{link}"
     style="background:#d3a84f;color:#1a1225;padding:13px 26px;border-radius:999px;
            text-decoration:none;font-weight:700">Set up my account →</a></p>
  <p style="color:#9a95ad;font-size:0.88rem">If this wasn't meant for you, you can ignore it.</p>
</div>''')


# ── Client import ─────────────────────────────────────────────────────────

@migration_bp.route('/clients', methods=['GET', 'POST'])
@owner_required
def clients():
    results = None
    if request.method == 'POST':
        f = request.files.get('csv_file')
        if not f or not f.filename:
            flash('Choose a CSV file first.', 'error')
            return redirect(url_for('migration.clients'))
        rows, err = _read_csv_rows(f)
        if err:
            flash(err, 'error')
            return redirect(url_for('migration.clients'))
        results = _import_client_rows(rows)
    return render_template('admin/migration_clients.html', results=results)


def _import_client_rows(rows):
    existing = {e.strip().lower() for (e,) in
               db.session.query(Client.email).all() if e and e.strip()}
    seen_in_file = set()
    created, skipped = [], []

    for i, row in enumerate(rows, start=2):
        name = (row.get('name') or '').strip()
        email = (row.get('email') or '').strip().lower()
        if not name or not email:
            skipped.append((i, name or email or '(blank row)', 'Missing a name or email.'))
            continue
        if not EMAIL_RE.match(email):
            skipped.append((i, name, f'"{email}" is not a valid email address.'))
            continue
        if email in existing or email in seen_in_file:
            skipped.append((i, name, f'{email} is already a customer (or listed twice in this file).'))
            continue
        seen_in_file.add(email)

        # "Client history" from another system has no reliable structured
        # shape here (see the module docstring on why booking rows aren't
        # synthesized) -- carried as a labelled note instead, never lost.
        notes_parts = []
        if row.get('notes'):
            notes_parts.append(row['notes'].strip())
        if row.get('history'):
            notes_parts.append(f"Imported history: {row['history'].strip()}")

        c = Client(
            name=name, email=email,
            phone=(row.get('phone') or '').strip() or None,
            address=(row.get('address') or '').strip() or None,
            city=(row.get('city') or '').strip() or None,
            zip_code=(row.get('zip') or row.get('zip_code') or '').strip() or None,
            notes='\n\n'.join(notes_parts) or None,
        )
        db.session.add(c)
        created.append((i, name, email))

    db.session.commit()
    return {'created': created, 'skipped': skipped}
