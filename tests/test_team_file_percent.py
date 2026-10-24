"""A percent-formatted Excel cell is stored as a fraction: 45% is 0.45. The team
importer read the fraction as plain text and filled the pay box with 0.45 -- a
valid rate that would pay a cleaner a hundredth of what the sheet showed."""
import io
import os
import sys
import tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/pct.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import setup_assistant


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


def sheet(header, rows, fmt=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    if fmt:
        for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
            for c in row:
                c.number_format = fmt
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


print('\n1. Percent-formatted commission comes over as percentage points')
rows, err = setup_assistant.read_team_file(
    'team.xlsx', sheet(['Name', 'Email', 'Commission'],
                       [['Ana Lopez', 'ana@example.com', 0.45],
                        ['Bo Chen', 'bo@example.com', 0.075]], fmt='0.0%'))
check(err is None, 'the file reads')
check((rows[0]['pay_type'], rows[0]['pay_rate']) == ('percent', '45'), '45% is 45, not 0.45')
check((rows[1]['pay_type'], rows[1]['pay_rate']) == ('percent', '7.5'), '7.5% is 7.5, with no float noise')

print('\n2. Everything that is not a percent cell reads as before')
rows, _ = setup_assistant.read_team_file(
    'team.xlsx', sheet(['Name', 'Email', 'Commission'], [['Ana Lopez', 'ana@example.com', 45]]))
check((rows[0]['pay_type'], rows[0]['pay_rate']) == ('percent', '45'), 'a plain 45 under a Commission heading is still 45')
rows, _ = setup_assistant.read_team_file(
    'team.xlsx', sheet(['Name', 'Email', 'Hourly rate'], [['Ana Lopez', 'ana@example.com', 22.5]]))
check((rows[0]['pay_type'], rows[0]['pay_rate']) == ('hourly', '22.5'), 'an hourly rate is untouched')
rows, _ = setup_assistant.read_team_file(
    'team.csv', b'Name,Email,Commission\nAna Lopez,ana@example.com,45%\n')
check((rows[0]['pay_type'], rows[0]['pay_rate']) == ('percent', '45'), 'CSV is untouched')
print('\nAll good')
