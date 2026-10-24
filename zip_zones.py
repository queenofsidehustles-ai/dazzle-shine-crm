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

# (low, high, zone) over the first three digits, inclusive. Where a state
# straddles a line, its prefixes are split along it, so a Montana or Alabama
# or Florida-panhandle business is not put an hour or two out.
_RANGES = [
    (5, 5, 'America/New_York'),          # Holtsville NY
    (6, 7, 'America/Puerto_Rico'),       # PR
    (8, 8, 'America/St_Thomas'),         # US Virgin Islands
    (9, 9, 'America/Puerto_Rico'),       # PR
    (10, 323, 'America/New_York'),       # New England to GA, FL (east)
    (324, 325, 'America/Chicago'),       # FL panhandle, west of the Apalachicola
    (326, 349, 'America/New_York'),      # FL
    (350, 369, 'America/Chicago'),       # AL
    (370, 372, 'America/Chicago'),       # TN: Nashville
    (373, 374, 'America/New_York'),      # TN: Chattanooga
    (375, 375, 'America/Chicago'),       # TN: Memphis
    (376, 379, 'America/New_York'),      # TN: the east, Knoxville
    (380, 385, 'America/Chicago'),       # TN: west and middle
    (386, 397, 'America/Chicago'),       # MS
    (398, 419, 'America/New_York'),      # GA (south), KY: Louisville and the east
    (420, 424, 'America/Chicago'),       # KY: the west
    (425, 462, 'America/New_York'),      # KY (east), OH, IN: Indianapolis
    (463, 464, 'America/Chicago'),       # IN: the northwest, Gary
    (465, 475, 'America/New_York'),      # IN
    (476, 477, 'America/Chicago'),       # IN: the southwest, Evansville
    (478, 499, 'America/New_York'),      # IN, MI
    (500, 576, 'America/Chicago'),       # IA, WI, MN, SD (east)
    (577, 577, 'America/Denver'),        # SD: the west, Rapid City
    (580, 585, 'America/Chicago'),       # ND
    (586, 586, 'America/Denver'),        # ND: the southwest, Dickinson
    (587, 588, 'America/Chicago'),       # ND
    (590, 599, 'America/Denver'),        # MT
    (600, 692, 'America/Chicago'),       # IL, MO, KS, NE
    (693, 693, 'America/Denver'),        # NE: the panhandle
    (700, 797, 'America/Chicago'),       # LA, AR, OK, TX
    (798, 799, 'America/Denver'),        # TX: El Paso
    (800, 831, 'America/Denver'),        # CO, WY
    (832, 834, 'America/Boise'),         # ID: the south
    (835, 835, 'America/Los_Angeles'),   # ID: Lewiston, the north-central
    (836, 837, 'America/Boise'),         # ID: the south, Boise
    (838, 838, 'America/Los_Angeles'),   # ID: the panhandle
    (840, 847, 'America/Denver'),        # UT
    (850, 865, 'America/Phoenix'),       # AZ -- no daylight saving
    (870, 884, 'America/Denver'),        # NM
    (889, 898, 'America/Los_Angeles'),   # NV
    (900, 961, 'America/Los_Angeles'),   # CA
    (967, 968, 'Pacific/Honolulu'),      # HI
    (969, 969, 'Pacific/Guam'),          # GU / MP
    (970, 994, 'America/Los_Angeles'),   # OR, WA
    (995, 999, 'America/Anchorage'),     # AK
]

# Prefixes that cross a zone line inside themselves, with the zones they
# cover. The range above gives the likelier one; a browser that is in one of
# these others is believed instead (resolve()).
# Each lists every name a browser on either side may report, regional ones
# included (a Menominee browser says America/Menominee, not America/Chicago).
MIXED = {
    324: ('America/Chicago', 'America/New_York'),    # FL: Panama City / Port St. Joe
    498: ('America/New_York', 'America/Detroit',     # MI: Upper Peninsula
          'America/Chicago', 'America/Menominee'),
    499: ('America/New_York', 'America/Detroit',
          'America/Chicago', 'America/Menominee'),
    586: ('America/Denver', 'America/Chicago',       # ND: Dickinson / Glen Ullin
          'America/North_Dakota/Center'),
    677: ('America/Chicago', 'America/Denver'),      # KS: the far west
    798: ('America/Denver', 'America/Chicago'),      # TX: El Paso / Alpine
    835: ('America/Los_Angeles', 'America/Boise'),   # ID: Lewiston / Idaho County south of the Salmon
    979: ('America/Los_Angeles', 'America/Boise'),   # OR: Malheur County
}

# Timezones we are willing to store, so a browser string we do not recognise
# cannot become the setting everything is scheduled against.
KNOWN = {z for _lo, _hi, z in _RANGES} | {
    'America/Detroit', 'America/Indiana/Indianapolis', 'America/Kentucky/Louisville',
    'America/Menominee', 'America/North_Dakota/Center', 'America/Juneau',
}


# What an owner can pick in Business Settings: every zone zone_for_zip() can
# give, under the name they would know it by. A zone the audit can recommend
# but nobody can choose would leave the fix to an edit of production data.
CHOICES = [
    ('America/New_York', 'Eastern (New York, Miami, Atlanta)'),
    ('America/Chicago', 'Central (Chicago, Dallas, Houston)'),
    ('America/Denver', 'Mountain (Denver, Salt Lake City, Boise)'),
    ('America/Phoenix', 'Arizona (no daylight saving)'),
    ('America/Los_Angeles', 'Pacific (Los Angeles, Seattle)'),
    ('America/Anchorage', 'Alaska'),
    ('Pacific/Honolulu', 'Hawaii (no daylight saving)'),
    ('America/Puerto_Rico', 'Atlantic (Puerto Rico, Virgin Islands)'),
    ('Pacific/Guam', 'Chamorro (Guam, Northern Mariana Islands)'),
]


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
    browser = (browser_zone or '').strip()
    five = digits(zip_code)
    if by_zip and len(five) >= 3 and browser in MIXED.get(int(five[:3]), ()):
        # A prefix that crosses a line: the browser picks the side.
        return browser, 'zip+browser'
    if by_zip:
        return by_zip, 'zip'
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
    'America/St_Thomas': 'Atlantic',
}


def label(zone):
    """What to call a timezone on screen. Never the raw name."""
    return LABELS.get(zone, (zone or '').split('/')[-1].replace('_', ' '))


def _same_clock(a, b):
    """Whether two zone names keep the same time all year (America/Detroit and
    America/New_York do): their offsets agree in January and in July."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        za, zb = ZoneInfo(a), ZoneInfo(b)
    except Exception:
        return False
    return all(datetime(2026, m, 15, 12, tzinfo=za).utcoffset()
               == datetime(2026, m, 15, 12, tzinfo=zb).utcoffset() for m in (1, 7))


def audit(zip_code, stored, default='America/New_York'):
    """What a company's stored timezone looks like against its ZIP:
    (status, expected). For the companies that signed up before the ZIP map
    was split along the lines, whose setting was stored from the old map.

      ok         the stored zone keeps the ZIP's time (or is one side of a
                 prefix that crosses a line)
      mismatch   it does not: their reminders and charges run at the wrong hour
      unset      none stored, so scheduling uses `default`, and the ZIP says
                 otherwise
      no-zip     no ZIP we can place, so nothing to compare
    """
    expected = zone_for_zip(zip_code)
    if not expected:
        return 'no-zip', ''
    stored = (stored or '').strip()
    effective = stored or default
    five = digits(zip_code)
    sides = MIXED.get(int(five[:3]), (expected,))
    if any(_same_clock(effective, zone) for zone in sides):
        return 'ok', expected
    return ('mismatch' if stored else 'unset'), expected

