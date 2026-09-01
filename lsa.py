"""Google Local Services Ads leads — importing them, working out which ones
turned into work, and following up by text with the ones that didn't.

LSA phone leads are a phone number and a timestamp. There is no name, no email
and no address, which is why they cannot live in Lead: that model requires an
email, and its nurture drip is email-only. Everything here keys on the last ten
digits of the phone number, because that is the only field that exists on both
sides of the question "did this person ever book?".

The follow-up is deliberately short — three texts over a week, and it stops the
moment anyone replies. These are people who rang a cleaning company and didn't
get booked; one nudge is a service, four is a nuisance.
"""
import csv
import io
from datetime import datetime, timedelta

import branding
from extensions import db
from models import LsaLead, Booking, Client


def phone10(p):
    """Last ten digits — the only form two systems can agree on."""
    digits = ''.join(ch for ch in (p or '') if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


# ── Importing the export ───────────────────────────────────────────────────────

# Google has renamed these columns before and localises some of them, so match
# on a distinctive fragment rather than the exact header. Order matters: the
# first fragment that appears in a header claims that column.
COLUMN_HINTS = [
    ('lead_id',       ('lead id', 'lead_id')),
    ('phone',         ('phone', 'customer number')),
    ('job_type',      ('job type',)),
    ('lead_type',     ('lead type',)),
    ('charge_status', ('charge status', 'charge')),
    ('location',      ('location',)),
    ('received_at',   ('lead received', 'received', 'date received')),
]

# The web table shows "8/24/26 7:06 PM" but the CSV export of the same page
# writes "Aug 24 2026" — so both have to be read, along with the obvious
# neighbours. A format that doesn't match costs a lead its date, which is what
# distinguishes two calls from the same number.
DATE_FORMATS = ('%m/%d/%y %I:%M %p', '%m/%d/%Y %I:%M %p', '%m/%d/%y', '%m/%d/%Y',
                '%b %d %Y', '%b %d, %Y', '%B %d %Y', '%B %d, %Y', '%d %b %Y',
                '%b %d %Y %I:%M %p', '%b %d, %Y %I:%M %p',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d')


def _map_columns(header):
    """Work out which column holds what. Returns {field: index}."""
    found = {}
    lowered = [(h or '').strip().lower() for h in header]
    for field, hints in COLUMN_HINTS:
        for i, h in enumerate(lowered):
            if i in found.values():
                continue
            if any(hint in h for hint in hints):
                found[field] = i
                break
    # Phone leads put the number in a column simply called "Customer". Only fall
    # back to it if nothing better matched, and only if it looks like a number —
    # on a message lead that same column holds a person's name.
    if 'phone' not in found:
        for i, h in enumerate(lowered):
            if h in ('customer', 'customer name') and i not in found.values():
                found['phone'] = i
                break
    return found


def parse_date(text):
    text = (text or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_csv(content):
    """Turn the raw LSA export into dicts. Returns (rows, problems).

    Rows without a usable phone number are reported rather than dropped in
    silence — a lead we can't text is something the owner should see, not
    something that quietly shrinks the number at the end."""
    if isinstance(content, bytes):
        content = content.decode('utf-8-sig', errors='replace')
    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
    except StopIteration:
        return [], ['The file is empty.']

    cols = _map_columns(header)
    if 'phone' not in cols:
        return [], ['No phone-number column found. Expected a column named '
                    'something like "Customer phone number".']

    rows, problems = [], []
    for n, raw in enumerate(reader, start=2):
        if not any((c or '').strip() for c in raw):
            continue

        def cell(field):
            i = cols.get(field)
            return (raw[i].strip() if i is not None and i < len(raw) else '')

        p = phone10(cell('phone'))
        if len(p) != 10:
            problems.append(f'Row {n}: no usable phone number ("{cell("phone")}") — skipped.')
            continue
        rows.append({
            'lead_id': cell('lead_id') or None,
            'phone': p,
            'job_type': cell('job_type'),
            'lead_type': cell('lead_type'),
            'charge_status': cell('charge_status'),
            'location': cell('location'),
            'received_at': parse_date(cell('received_at')),
        })
    return rows, problems


def synthetic_id(phone, received_at):
    """An identity for exports that carry no lead ID of their own.

    The CSV download of the Leads page has no ID column — that only appears in
    the web table — so re-importing an overlapping range would otherwise add
    everyone a second time. Number plus the day of the call is the best
    available substitute: it keeps two calls from the same number on different
    days apart, which is a real and common case.

    A row whose date failed to parse gets 'unknown', which deliberately
    collapses repeat calls from that number into one record. Merging two leads
    is recoverable; texting the same person twice on the same day is not."""
    day = received_at.strftime('%Y-%m-%d') if received_at else 'unknown'
    return f'{phone}@{day}'


def import_rows(rows):
    """Save parsed rows. Returns (added, updated).

    The lead id is the identity — Google's own where the export has one, and a
    synthetic one built from number and date where it doesn't. Re-importing an
    overlapping export is the normal case, since she'll download the same range
    each time, so a lead already here is refreshed rather than duplicated and
    its sequence state is left completely alone."""
    added = updated = 0
    for r in rows:
        r = dict(r)
        if not r['lead_id']:
            r['lead_id'] = synthetic_id(r['phone'], r['received_at'])
        existing = LsaLead.query.filter_by(lead_id=r['lead_id']).first()
        if existing:
            existing.job_type = r['job_type'] or existing.job_type
            existing.location = r['location'] or existing.location
            existing.lead_type = r['lead_type'] or existing.lead_type
            existing.charge_status = r['charge_status'] or existing.charge_status
            existing.received_at = r['received_at'] or existing.received_at
            # Track is deliberately not refreshed. She may have corrected it by
            # hand — she was on the call — and a re-import must not replace what
            # she knows with what Google's billing implies. Only fill it in if
            # it has never been set, which covers rows imported before tracks.
            if not existing.track:
                existing.track = default_track(existing.charge_status)
            updated += 1
        else:
            db.session.add(LsaLead(track=default_track(r['charge_status']), **r))
            added += 1
    db.session.commit()
    return added, updated


# ── Did they book? ─────────────────────────────────────────────────────────────

def match_bookings(leads=None):
    """Match leads against bookings by phone number. Returns how many booked.

    Matching is done in memory off two indexes rather than a query per lead:
    a few hundred leads against a few hundred bookings is nothing, and it keeps
    the whole comparison in one place where the normalisation is obviously the
    same on both sides.

    A booking made *before* the call isn't evidence the call converted, but it
    does mean this is an existing customer — and either way she does not want a
    "you never booked with us" text going to someone who has. So any booking on
    that number counts."""
    leads = leads if leads is not None else LsaLead.query.all()
    by_phone = {}
    for b in Booking.query.all():
        p = phone10(b.phone)
        if p:
            by_phone.setdefault(p, b)
    client_phones = {phone10(c.phone) for c in Client.query.all() if phone10(c.phone)}

    now = datetime.utcnow()
    booked = 0
    for lead in leads:
        b = by_phone.get(lead.phone)
        lead.booked = bool(b) or lead.phone in client_phones
        lead.booking_id = b.id if b else None
        lead.booked_checked_at = now
        if lead.booked:
            booked += 1
            # Someone who has since booked should not still be being chased.
            if lead.in_sequence:
                lead.seq_stopped = 'booked'
    db.session.commit()
    return booked


# ── The follow-up sequence ─────────────────────────────────────────────────────
#
# Three texts. Day 0 when she starts it, then day 3, then day 7. Each one has to
# stand on its own — someone reading the third has probably forgotten the first.

SEQUENCE = [
    (0, 'first'),
    (4, 'second'),
    (8, 'final'),
]

# Two different conversations, because these are two different people.
#
# A lead Google didn't charge for is one where the call never really connected —
# those people have never spoken to us, and "sorry we missed you" is exactly
# right. A charged lead is someone who got through, talked to the owner and was
# quoted a price, and then chose somebody else. Sending that person an apology
# for not connecting reads as though we don't remember them, which is worse than
# not texting at all.
MISSED, QUOTED = 'missed', 'quoted'
# What each conversation is, in words that do not assume a phone call from
# a Google ad. A voicemail, a web form and a text nobody answered are all
# the first one; an emailed price request is the second.
TRACKS = [(MISSED, 'Missed call or message'),
          (QUOTED, 'Asked for a price')]

# Google's billing status is the only signal in the export about which happened,
# and it's a good one: it charges for calls that connected. It is only a
# default, though — the owner was on the calls and can say otherwise.
MISSED_STATUSES = ('not charged', 'credited')


def default_track(charge_status):
    return MISSED if (charge_status or '').strip().lower() in MISSED_STATUSES else QUOTED


# The wording lives in settings so it can be changed without a deploy; these are
# only what a fresh install starts with. Placeholders are filled by message_for.
DEFAULT_MESSAGES = {
    (MISSED, 1): ("Hi, this is {biz} — you called us about a cleaning on {called} and "
                  "we're sorry we didn't get to connect. Are you still looking for "
                  "help? Reply here and I'll get you a price today. "
                  "Reply STOP to opt out."),
    (MISSED, 2): ("Hi again from {biz}. If a cleaning is still on your list, we have "
                  "openings this week — just reply with your bedrooms and bathrooms "
                  "and I'll text you a quote. Reply STOP to opt out."),
    (MISSED, 3): ("Last note from {biz} — I don't want to keep filling up your phone. "
                  "If you'd still like a cleaning, you can book anytime at {link}. "
                  "Otherwise, all the best! Reply STOP to opt out."),

    # The quoted track leads with the guarantee. These people already heard a
    # price and went elsewhere, so repeating the price achieves nothing — what
    # they were weighing was whether to trust a stranger in their house, and
    # taking the risk off them is the strongest thing we can say. The last one
    # deliberately leaves a door open rather than closing: a cheap cleaner
    # falling through is the single most likely reason they come back.
    # The guarantee is worded to match what customer_terms actually promises —
    # tell us within 24 hours and we re-clean at no charge. A text that promised
    # more than the terms she'll later ask them to accept would be a problem
    # exactly when it mattered, and the 24 hours makes it sound like a real
    # policy rather than a slogan.
    (QUOTED, 1): ("Hi, this is {biz} — I quoted you for a cleaning on {called}. If "
                  "you're still deciding, one thing worth knowing: if something's "
                  "not right, tell us within 24 hours and we come back and re-clean "
                  "it free. We'd much rather fix it than argue about it. Want me to "
                  "hold you a spot? Reply STOP to opt out."),
    # Every message in a marketing sequence carries the opt-out, not just the
    # first and last. This one was the only one of the six without it.
    (QUOTED, 2): ("Hi again from {biz}. We're insured, every cleaner is "
                  "background-checked, and you get the same person each visit rather "
                  "than a stranger every time. Happy to re-quote if your dates or "
                  "your place have changed. Reply STOP to opt out."),
    (QUOTED, 3): ("Last note from me. If whoever you went with didn't work out — it "
                  "happens more than you'd think — we're here, and we can usually "
                  "get you in the same week. {link} Reply STOP to opt out."),
}


def setting_key(track, step):
    return f'lsa_msg_{track}_{step}'


def template_for(track, step):
    """The wording for one message — hers if she has edited it, ours if not."""
    from models import BusinessSetting
    default = DEFAULT_MESSAGES.get((track, step), '')
    saved = BusinessSetting.get(setting_key(track, step), '')
    return (saved or '').strip() or default


def save_template(track, step, body):
    """Store edited wording. Saving it back to the default, or blanking it,
    clears the override rather than storing a copy that would then be frozen
    if the default ever improves."""
    from models import BusinessSetting
    from extensions import db as _db
    body = (body or '').strip()
    BusinessSetting.set(setting_key(track, step),
                        '' if body == DEFAULT_MESSAGES.get((track, step), '').strip() else body)
    _db.session.commit()


def render(body, lead):
    """Fill the placeholders. Unknown ones are left alone rather than blowing up
    a send — a stray brace in her wording must not cost the whole run."""
    called = lead.received_at.strftime('%b %-d') if lead.received_at else 'recently'
    values = {'biz': branding.biz_name(), 'link': branding.booking_link(),
              'called': called, 'phone': branding.phone()}
    out = body or ''
    for k, v in values.items():
        out = out.replace('{' + k + '}', str(v or ''))
    return out.strip()


def message_for(step, lead):
    """The text for step N (1-based) on this lead's track. One place, so the
    preview on the screen and the text that actually sends cannot drift."""
    track = getattr(lead, 'track', None) or QUOTED
    return render(template_for(track, step), lead)


def start_sequence(lead):
    """Put a lead into the sequence. Does not send anything — the first text
    goes out on the next run, which keeps every send on one code path and means
    a mistake can be undone before it reaches anyone."""
    if lead.booked or lead.seq_started_at:
        return False
    lead.seq_started_at = datetime.utcnow()
    lead.seq_step = 0
    lead.seq_stopped = None
    db.session.commit()
    return True


def stop_sequence(lead, reason='manual'):
    if not lead.in_sequence:
        return False
    lead.seq_stopped = reason
    db.session.commit()
    return True


def due_now(now=None):
    """Leads whose next text is due. Kept separate from sending so the screen
    can show exactly what the next run would do."""
    now = now or datetime.utcnow()
    out = []
    for lead in LsaLead.query.filter(LsaLead.seq_started_at.isnot(None),
                                     LsaLead.seq_stopped.is_(None)).all():
        step = lead.seq_step or 0
        if step >= len(SEQUENCE):
            continue
        wait_days = SEQUENCE[step][0]
        base = lead.last_seq_at or lead.seq_started_at
        if step == 0:
            out.append(lead)
        elif base and now - base >= timedelta(days=wait_days - SEQUENCE[step - 1][0]):
            out.append(lead)
    return out


def run_sequence(now=None, limit=200):
    """Send whatever is due. Returns a summary dict.

    Every guard is re-checked at send time rather than trusted from when the
    sequence started: days have passed, and in that time they may have booked,
    replied, or told us to stop."""
    from notifications import send_marketing_sms, sms_opted_out
    now = now or datetime.utcnow()
    sent = skipped = failed = 0

    for lead in due_now(now)[:limit]:
        if lead.booked:
            lead.seq_stopped = 'booked'
            skipped += 1
            continue
        if sms_opted_out(lead.phone):
            lead.seq_stopped = 'opted_out'
            skipped += 1
            continue
        if _has_replied(lead):
            lead.seq_stopped = 'replied'
            skipped += 1
            continue

        step = (lead.seq_step or 0) + 1
        ok, _detail = send_marketing_sms(lead.phone, message_for(step, lead))
        if ok:
            lead.seq_step = step
            lead.last_seq_at = now
            if step >= len(SEQUENCE):
                lead.seq_stopped = 'finished'
            sent += 1
        else:
            # Leave the step where it is so the next run tries again, rather
            # than burning a message on a failure the customer never saw.
            failed += 1
        db.session.commit()

    return {'sent': sent, 'skipped': skipped, 'failed': failed}


def _has_replied(lead):
    """Has this number texted us since the sequence began?

    The inbound webhook already stops a sequence the moment a reply lands, so
    this is a backstop for replies that arrived while the webhook was down, or
    before this lead was put into a sequence at all."""
    from models import Message
    since = lead.seq_started_at or lead.created_at
    q = Message.query.filter_by(phone=lead.phone, direction='in')
    if since:
        q = q.filter(Message.created_at >= since)
    return q.first() is not None
