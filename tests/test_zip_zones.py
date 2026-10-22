"""ZIP prefixes are split where a state crosses a time-zone line.

The first map put every prefix from 300 to 499 in Eastern and 500 to 599 in
Central, so Alabama (Huntsville included), the Florida panhandle, western
Tennessee and Kentucky were an hour ahead, Montana an hour behind, and Puerto
Rico and the Virgin Islands in New York. Signup stores what the ZIP says, so
reminders and charges ran off for those businesses with nothing to notice.
"""
import os, sys
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import zip_zones as z

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


print('\n1. Places that straddle a line are on the right side of it')
for zip_code, zone, where in (
        ('35801', 'America/Chicago', 'Huntsville, AL'),
        ('36104', 'America/Chicago', 'Montgomery, AL'),
        ('32501', 'America/Chicago', 'Pensacola, FL (panhandle)'),
        ('32301', 'America/New_York', 'Tallahassee, FL'),
        ('37203', 'America/Chicago', 'Nashville, TN'),
        ('37902', 'America/New_York', 'Knoxville, TN'),
        ('38103', 'America/Chicago', 'Memphis, TN'),
        ('42001', 'America/Chicago', 'Paducah, KY'),
        ('40202', 'America/New_York', 'Louisville, KY'),
        ('46402', 'America/Chicago', 'Gary, IN'),
        ('46204', 'America/New_York', 'Indianapolis, IN'),
        ('47708', 'America/Chicago', 'Evansville, IN'),
        ('59101', 'America/Denver', 'Billings, MT'),
        ('57701', 'America/Denver', 'Rapid City, SD'),
        ('57104', 'America/Chicago', 'Sioux Falls, SD'),
        ('79901', 'America/Denver', 'El Paso, TX'),
        ('75201', 'America/Chicago', 'Dallas, TX'),
        ('83814', 'America/Los_Angeles', "Coeur d'Alene, ID"),
        ('83702', 'America/Boise', 'Boise, ID'),
        ('83501', 'America/Los_Angeles', 'Lewiston, ID (Pacific)'),
        ('83201', 'America/Boise', 'Pocatello, ID'),
        ('83301', 'America/Boise', 'Twin Falls, ID'),
        ('00901', 'America/Puerto_Rico', 'San Juan, PR'),
        ('00802', 'America/St_Thomas', 'St Thomas, VI'),
        ('10001', 'America/New_York', 'New York, NY'),
        ('90210', 'America/Los_Angeles', 'Beverly Hills, CA'),
        ('85004', 'America/Phoenix', 'Phoenix, AZ')):
    got = z.zone_for_zip(zip_code)
    check(got == zone, f'{where} {zip_code}: {z.label(zone)} (got {got})')

print('\n2. A prefix that crosses a line inside itself asks the browser')
check(z.resolve('49801', 'America/Chicago') == ('America/Chicago', 'zip+browser'),
      'Upper Peninsula with a Central browser: Central')
check(z.resolve('49801', 'America/Denver') == ('America/New_York', 'zip'),
      'but a browser in neither of its zones does not override the ZIP')
check(z.resolve('59101', 'America/New_York') == ('America/Denver', 'zip'),
      'and a single-zone prefix keeps the ZIP, wherever the browser is')
for zip_code, browser, where in (
        ('32456', 'America/New_York', 'Port St. Joe, FL (Eastern, in a Central prefix)'),
        ('58639', 'America/Chicago', 'Glen Ullin, ND (Central, in a Mountain prefix)'),
        ('79830', 'America/Chicago', 'Alpine, TX (Central, beside El Paso)'),
        ('49858', 'America/Menominee', 'Menominee, MI, reporting its regional name'),
        ('49855', 'America/Detroit', 'Marquette, MI, reporting its regional name')):
    check(z.resolve(zip_code, browser) == (browser, 'zip+browser'),
          f"{where}: the browser's side of the line")

print('\n3. The map itself')
prev = -1
ordered = True
for lo, hi, _zone in z._RANGES:
    ordered = ordered and lo > prev and lo <= hi
    prev = hi
check(ordered, 'ranges ascend without overlapping')
check(all(ZoneInfo(zone) for zone in z.KNOWN), 'every zone it can store is a real one')
check(all(zone in z.KNOWN for zones in z.MIXED.values() for zone in zones),
      'and so is every zone a mixed prefix can resolve to')

print('\n4. Auditing a stored zone against its ZIP')
check(z.audit('35801', 'America/New_York') == ('mismatch', 'America/Chicago'),
      'Huntsville stored as Eastern is a mismatch')
check(z.audit('35801', '') == ('unset', 'America/Chicago'),
      'and with nothing stored, the Eastern default is too')
check(z.audit('10001', 'America/Detroit')[0] == 'ok', 'a zone that keeps the same clock is fine')
check(z.audit('49801', 'America/Menominee')[0] == 'ok',
      'either side of a prefix that crosses a line is fine')
check(z.audit('', 'America/Chicago') == ('no-zip', ''), 'no ZIP, nothing to compare')
check(z.audit('83501', 'America/Los_Angeles')[0] == 'ok'
      and z.audit('83549', 'America/Boise')[0] == 'ok',
      'Lewiston on Pacific is fine, and so is the south of Idaho County on Mountain')

print('\n5. Whatever the audit recommends, an owner can pick')
choosable = {zone for zone, _label in z.CHOICES}
check(all(any(z._same_clock(zone, c) for c in choosable) for _lo, _hi, zone in z._RANGES),
      'every zone a ZIP gives keeps the clock of one in Business Settings')
check(all(ZoneInfo(zone) for zone in choosable), 'and each of those is a real zone')
import setup_assistant
offered = {zone for zone, _label in setup_assistant.TIMEZONES.values()}
check(all(any(z._same_clock(zone, c) for c in offered) for _lo, _hi, zone in z._RANGES),
      'and the setup assistant can offer one with the same clock for every ZIP')

if failures:
    print(f'\n❌ {len(failures)} failed')
    raise SystemExit(1)
print('\n✅ The ZIP puts a business in its own time zone.')
