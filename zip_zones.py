"""Which timezone a US ZIP code is in, without asking.

The timezone is the setting that fails most quietly in the whole product: left
alone it is America/New_York, so a business in Texas sends tomorrow's
reminders an hour early forever and has nothing to suspect. It is also a
question nobody should have to answer -- the browser knows, and the ZIP knows,
and between them they are right far more often than a dropdown somebody clicks
through to get rid of.

ZIP prefixes, not a full table. The first three digits are allocated
geographically, so a range is enough to place a ZIP in a zone, and the whole
map fits in a screen instead of a 40,000-row dataset nobody will maintain.

Where the two disagree -- somebody signing up from a hotel in another state --
the ZIP wins, because that is where the cleaning happens.
"""

# (low, high, zone) over the first three digits, inclusive.
_RANGES = [
    (6, 6, 'America/Puerto_Rico'),       # PR / VI
    (7, 199, 'America/New_York'),        # New England down through PA
    (200, 299, 'America/New_York'),      # DC, VA, WV, NC, SC
    (300, 399, 'America/New_York'),      # GA, FL, AL (eastern), TN (eastern)
    (400, 499, 'America/New_York'),      # KY, OH, IN (mostly)
    (500, 599, 'America/Chicago'),       # IA, MN, MT, ND, SD
    (600, 699, 'America/Chicago'),       # IL, MO, KS
    (700, 799, 'America/Chicago'),       # LA, AR, OK, TX
    (800, 816, 'America/Denver'),        # CO
    (820, 831, 'America/Denver'),        # WY, ID (east), UT
    (832, 838, 'America/Boise'),         # ID panhandle
    (840, 847, 'America/Denver'),        # UT
    (850, 865, 'America/Phoenix'),       # AZ -- no daylight saving
    (870, 884, 'America/Denver'),        # NM
    (889, 898, 'America/Los_Angeles'),   # NV
    (900, 961, 'America/Los_Angeles'),   # CA
    (967, 968, 'Pacific/Honolulu'),      # HI
    (969, 969, 'Pacific/Guam'),          # GU / MP
    (970, 979, 'America/Los_Angeles'),   # OR, WA
    (980, 994, 'America/Los_Angeles'),   # WA, ID (north)
    (995, 999, 'America/Anchorage'),     # AK
]

# Timezones we are willing to store, so a browser string we do not recognise
# cannot become the setting everything is scheduled against.
KNOWN = {z for _lo, _hi, z in _RANGES} | {
    'America/Detroit', 'America/Indiana/Indianapolis', 'America/Kentucky/Louisville',
    'America/Menominee', 'America/North_Dakota/Center', 'America/Juneau',
}


def digits(zip_code):
    """The first five digits of whatever was typed, or ''."""
    out = ''.join(c for c in str(zip_code or '') if c.isdigit())
    return out[:5]


def zone_for_zip(zip_code):
    """The timezone for a ZIP, or '' when it is not one we can place."""
    five = digits(zip_code)
    if len(five) < 3:
        return ''
    prefix = int(five[:3])
    for lo, hi, zone in _RANGES:
        if lo <= prefix <= hi:
            return zone
    return ''


def resolve(zip_code='', browser_zone=''):
    """The timezone to use, and where it came from: (zone, source).

    The ZIP wins over the browser. Somebody signing up from a hotel in another
    state is still cleaning houses at home, and the browser is the one of the
    two that can be somewhere else entirely.
    """
    by_zip = zone_for_zip(zip_code)
    if by_zip:
        return by_zip, 'zip'
    browser = (browser_zone or '').strip()
    if browser in KNOWN:
        return browser, 'browser'
    return '', ''


LABELS = {
    'America/New_York': 'Eastern',
    'America/Detroit': 'Eastern',
    'America/Indiana/Indianapolis': 'Eastern',
    'America/Kentucky/Louisville': 'Eastern',
    'America/Chicago': 'Central',
    'America/Menominee': 'Central',
    'America/North_Dakota/Center': 'Central',
    'America/Denver': 'Mountain',
    'America/Boise': 'Mountain',
    'America/Phoenix': 'Arizona',
    'America/Los_Angeles': 'Pacific',
    'America/Anchorage': 'Alaska',
    'America/Juneau': 'Alaska',
    'Pacific/Honolulu': 'Hawaii',
    'Pacific/Guam': 'Guam',
    'America/Puerto_Rico': 'Puerto Rico',
}


def label(zone):
    """What to call a timezone on screen. Never the raw name."""
    return LABELS.get(zone, (zone or '').split('/')[-1].replace('_', ' '))
