"""When a job's appointment actually starts, in the business's own timezone.

Customers get nervous when a card is charged before anyone turns up, which is
fair — the work hasn't started. Charging on a single clock time for everybody
only helps whoever happens to be booked at that hour: move the run to 9am and
the 1pm customer is still charged four hours early.

So charging follows each booking's own appointment time instead.

Two things make this less trivial than it sounds:

The server runs on UTC and the business does not. In Orlando the server is four
or five hours ahead depending on the season, so at 8pm local the server already
believes it is tomorrow. Comparing a local appointment time against a UTC clock
would charge people on the wrong day.

And the appointment time is a free-text box — "10:00 AM", "10am", "morning",
"between 9 and 11". Anything unreadable falls back to a default hour rather than
being guessed at, because guessing early is the exact problem being fixed.
"""
import os
import re
from datetime import datetime, timezone

DEFAULT_TZ = 'America/New_York'
DEFAULT_CHARGE_HOUR = 9      # used when a booking has no readable time


def _setting(key, default=''):
    try:
        from models import BusinessSetting
        return (BusinessSetting.get(key) or '').strip() or default
    except Exception:
        return default


def business_timezone():
    name = _setting('timezone') or os.environ.get('BUSINESS_TZ') or DEFAULT_TZ
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(DEFAULT_TZ)
        except Exception:
            return timezone.utc      # last resort; better than crashing a cron


def local_now():
    """Now, where the business is."""
    return datetime.now(timezone.utc).astimezone(business_timezone())


def local_today():
    """Today's date where the business is — not where the server is."""
    return local_now().date()


_TIME_PATTERNS = [
    # 10:00 AM · 10:00am · 10.30 pm
    re.compile(r'(?P<h>\d{1,2})[:.](?P<m>\d{2})\s*(?P<ap>[ap])\.?m\.?', re.I),
    # 10 AM · 10am
    re.compile(r'(?P<h>\d{1,2})\s*(?P<ap>[ap])\.?m\.?', re.I),
    # 14:30 (24-hour)
    re.compile(r'(?P<h>\d{1,2}):(?P<m>\d{2})'),
    # A bare hour — "between 9 and 11", "9 - 11", "starts 2". Takes the first
    # number and reads it as a working hour, so a range starts when the customer
    # was told somebody would arrive rather than falling back to the default.
    re.compile(r'\b(?P<h>\d{1,2})\b'),
]

# A bare number has no am/pm, so it is read the way a cleaning business runs:
# 7-11 in the morning, 12 midday, 1-6 in the afternoon.
def _bare_hour(hour):
    if 7 <= hour <= 12:
        return hour
    if 1 <= hour <= 6:
        return hour + 12
    return None

# Rough words people actually type into a time box.
_WORDS = {'morning': 9, 'afternoon': 13, 'evening': 17, 'noon': 12, 'midday': 12}


def parse_time(text):
    """(hour, minute) from free text, or None if it can't be read confidently.

    Only the FIRST time in a range is used: "between 9 and 11" starts at 9, which
    is when the customer expects somebody."""
    if not text:
        return None
    raw = str(text).strip().lower()
    if not raw:
        return None

    for word, hour in _WORDS.items():
        if word in raw:
            return (hour, 0)

    for pattern in _TIME_PATTERNS:
        m = pattern.search(raw)
        if not m:
            continue
        hour = int(m.group('h'))
        minute = int(m.groupdict().get('m') or 0)
        ap = (m.groupdict().get('ap') or '').lower()
        if ap == 'p' and hour != 12:
            hour += 12
        elif ap == 'a' and hour == 12:
            hour = 0
        elif not ap and 'm' not in m.groupdict():
            resolved = _bare_hour(hour)
            if resolved is None:
                continue
            hour = resolved
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    return None


def default_charge_hour():
    try:
        return max(0, min(23, int(_setting('charge_hour', str(DEFAULT_CHARGE_HOUR)))))
    except (TypeError, ValueError):
        return DEFAULT_CHARGE_HOUR


def appointment_start(booking, on_date=None):
    """When this booking's slot begins, in business-local time."""
    from datetime import datetime as _dt
    day = on_date or local_today()
    parsed = parse_time(getattr(booking, 'preferred_time', None))
    hour, minute = parsed if parsed else (default_charge_hour(), 0)
    return _dt.combine(day, _dt.min.time()).replace(
        hour=hour, minute=minute, tzinfo=business_timezone())


def due_for_charge(booking, now=None):
    """True once this booking's appointment time has arrived.

    A job scheduled for a day other than today is never due — a cron running
    hourly must not reach forward into tomorrow or back into last week."""
    now = now or local_now()
    today = now.date().isoformat()
    if (getattr(booking, 'preferred_date', None) or '') != today:
        return False
    return now >= appointment_start(booking, now.date())


def describe(booking):
    """'charges at 1:00 PM' — for showing on the booking page."""
    parsed = parse_time(getattr(booking, 'preferred_time', None))
    hour, minute = parsed if parsed else (default_charge_hour(), 0)
    suffix = 'AM' if hour < 12 else 'PM'
    display = hour % 12 or 12
    when = f'{display}:{minute:02d} {suffix}'
    return when if parsed else f'{when} (no arrival time set)'


def to_local(dt):
    """A stored timestamp as local time.

    Everything is written with utcnow(), so the values in the database are naive
    UTC. Displaying them raw shows a 9am job as 13:00, which looks wrong to the
    owner and to anyone reviewing a dispute."""
    if dt is None:
        return None
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(business_timezone())


def stamp(dt, with_utc=True):
    """'5 August 2026 at 9:42 AM EDT (13:42 UTC)'.

    Local time first, because that is the time the work actually happened and
    the time on the owner's own photographs and phone records. UTC alongside it
    so a reviewer cross-checking against Stripe — which reports in UTC — can line
    the two up without having to trust anyone's arithmetic."""
    if dt is None:
        return '—'
    local = to_local(dt)
    label = local.strftime('%Z') or 'local'
    out = local.strftime(f'%-d %B %Y at %-I:%M %p {label}')
    if with_utc:
        utc = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        out += utc.strftime(' (%H:%M UTC)')
    return out


def short_stamp(dt):
    """'5 Aug 2026, 9:42 AM' — for table rows, where a full stamp is too much."""
    if dt is None:
        return '—'
    return to_local(dt).strftime('%-d %b %Y, %-I:%M %p')
