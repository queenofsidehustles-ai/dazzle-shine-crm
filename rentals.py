"""Short-term rental turnovers, read from the calendar the host already has.

Airbnb, VRBO and Booking.com all publish a per-listing iCal feed. The host
copies that URL out of their own dashboard and pastes it in; there is no
partnership to negotiate and no API key to hold. We read the feed, and every
check-out becomes a cleaning job on that date.

Why parse it here rather than add a library: an Airbnb feed is a handful of
all-day VEVENTs with a UID, a DTSTART and a DTEND. The hard parts of iCal —
timezones, recurrence rules, alarms — do not appear in one. A hundred lines
that handle exactly what these feeds contain is easier to reason about at 3am
than a dependency that handles everything.

The reliability rule this file exists to keep: never create the same turnover
twice, and never silently skip one. A duplicate is an argument with a customer.
A miss is a guest opening the door on somebody else's weekend.
"""
import re
from datetime import datetime, date, timedelta

import requests

from extensions import db

FETCH_TIMEOUT = 20
# A feed that has not been read in this long is worth saying so about on screen.
STALE_AFTER = timedelta(hours=12)


def _unfold(text):
    """iCal wraps long lines and continues them with a leading space or tab."""
    return re.sub(r'\r?\n[ \t]', '', text or '')


def _parse_date(value):
    """DTSTART/DTEND as a plain date. Feeds like these are all-day events.

    A date-time form (20260312T110000Z) is accepted too and truncated to the
    day, because what matters here is which day somebody leaves.
    """
    v = (value or '').strip()
    m = re.match(r'^(\d{4})(\d{2})(\d{2})', v)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_ical(text):
    """Every stay in the feed, as {uid, start, end, summary}.

    `end` is the check-out day. For an all-day VEVENT the DTEND is exclusive by
    the spec, and Airbnb writes the check-out date there — so it is already the
    day the cleaner needs, and must not be shifted.
    """
    out = []
    for block in re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', _unfold(text or ''), re.S):
        fields = {}
        for line in block.splitlines():
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            fields[key.split(';')[0].strip().upper()] = val.strip()
        start, end = _parse_date(fields.get('DTSTART')), _parse_date(fields.get('DTEND'))
        if not end:
            continue
        out.append({
            'uid': (fields.get('UID') or f'{start}-{end}')[:300],
            'start': start,
            'end': end,
            'summary': (fields.get('SUMMARY') or '')[:120],
        })
    out.sort(key=lambda e: (e['end'] or date.min))
    return out


def _blocked(summary):
    """A host's own block-out is not a guest, so it is not a turnover.

    Airbnb writes "Airbnb (Not available)" for dates the host closed off
    themselves. Cleaning after nobody has stayed is work nobody asked for.
    """
    s = (summary or '').lower()
    return 'not available' in s or s.strip() in ('blocked', 'unavailable')


def fetch(url):
    r = requests.get(url, timeout=FETCH_TIMEOUT,
                     headers={'User-Agent': 'Akye/1.0 (+https://www.akyehq.com)'})
    r.raise_for_status()
    return r.text


def turnovers_from(events, horizon_days=120, today=None):
    """Stays that end from today onward, each marked if it is a same-day turn.

    Same-day is the one worth knowing about: the guest leaves at eleven and the
    next arrives at three, so the clean has a hard deadline rather than a day.
    """
    today = today or date.today()
    limit = today + timedelta(days=horizon_days)
    starts = sorted(e['start'] for e in events if e['start'] and not _blocked(e['summary']))
    out = []
    for e in events:
        if _blocked(e['summary']) or not e['end']:
            continue
        if e['end'] < today or e['end'] > limit:
            continue
        nxt = next((s for s in starts if s >= e['end']), None)
        out.append({**e, 'next_checkin': nxt, 'same_day': nxt == e['end']})
    return out


def sync_property(prop, today=None):
    """Read one property's feed and create the jobs it implies.

    Returns (created, skipped, error). An error is recorded on the property and
    returned rather than raised: one host's broken link must not stop the other
    nineteen from being cleaned.
    """
    from models import Booking, RentalTurnover
    today = today or date.today()
    try:
        events = parse_ical(fetch(prop.ical_url))
    except Exception as e:
        prop.last_error = f'{type(e).__name__}: {str(e)[:160]}'
        prop.last_synced_at = datetime.utcnow()
        db.session.commit()
        return 0, 0, prop.last_error

    created = skipped = 0
    for t in turnovers_from(events, today=today):
        iso = t['end'].isoformat()
        seen = RentalTurnover.query.filter_by(
            property_id=prop.id, uid=t['uid'], checkout_on=iso).first()
        if seen:
            skipped += 1
            continue
        b = Booking(
            name=prop.name,
            service_type=prop.service_type or 'standard',
            preferred_date=iso,
            preferred_time=prop.clean_time or '11:00 AM',
            address=prop.address or '',
            city=prop.city or '',
            zip_code=prop.zip_code or '',
            client_id=prop.client_id,
            price=prop.price,
            status='confirmed',
            notes=('Same-day turnover — next guest arrives today.'
                   if t['same_day'] else 'Turnover clean.'),
        )
        db.session.add(b)
        db.session.flush()
        db.session.add(RentalTurnover(
            property_id=prop.id, uid=t['uid'], checkout_on=iso,
            next_checkin_on=t['next_checkin'].isoformat() if t['next_checkin'] else None,
            same_day=bool(t['same_day']), booking_id=b.id,
            created_at=datetime.utcnow()))
        created += 1

    prop.last_synced_at = datetime.utcnow()
    prop.last_error = None
    db.session.commit()
    return created, skipped, None


def sync_all(today=None):
    from models import RentalProperty
    totals = {'properties': 0, 'created': 0, 'skipped': 0, 'errors': []}
    for prop in RentalProperty.query.filter_by(is_active=True).all():
        totals['properties'] += 1
        made, skip, err = sync_property(prop, today=today)
        totals['created'] += made
        totals['skipped'] += skip
        if err:
            totals['errors'].append(f'{prop.name}: {err}')
    return totals
