"""Nana, sitting next to a brand-new owner while she sets up.

## Why this exists

Signing up is the easy part. The getting-started list says what to do next,
but it is still six pages of forms, and somebody who signed up from her phone
between jobs does not know which box on which page matters. Onboarding is
where new companies stall, so this turns the list into a conversation: one
question at a time, in plain words, with Nana filling the forms in for her.

## The same rule as everywhere else Nana works

Nothing is saved because a model said so. When the owner gives her details,
Nana offers a card with exactly what will be written, and it is only written
when the owner presses Save. The card is a token (proposals.py), so what is
saved is what was on the card, not what the page posted back.

Some things she will not touch at all. Bank and card details, passwords and
anything that moves money are typed by the owner, on the owner's own screen.
Nana points at the page and stops.

## Paid for by the platform's Claude API credits

This talks to the Claude API directly (ANTHROPIC_API_KEY), like the rest of
Nana when that key is set, because the Claude Max plan behind Akye comes
with monthly Claude API credits. Haiku is plenty for this job: the hard
part is asking the right next question, not deep reasoning. A full setup
conversation is a few cents.

Without a key, or in the demo, the chat simply does not appear and the
getting-started list works exactly as it always has.
"""
import json
import os
import re

import assistant

NAME = assistant.NAME

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
MODEL = os.environ.get('SETUP_ASSISTANT_MODEL', 'claude-haiku-4-5')

# Messages per company per month. Setup takes twenty or thirty; the cap is
# there so one confused afternoon cannot spend somebody else's credits.
MONTHLY_LIMIT = int(os.environ.get('SETUP_ASSISTANT_MONTHLY_LIMIT') or 80)

# Model calls within one message: look at progress, offer a card, answer.
MAX_STEPS = 5
DEADLINE_SECONDS = 50

# Conversation carried into each call. Enough for "that's my cell" to mean
# something; short enough that a long chat does not become a long bill.
HISTORY_MESSAGES = 14

# The conversation is kept in the database, not the login cookie: a cookie
# over 4KB is silently dropped by the browser, and the login goes with it.
MAX_KEPT = 30


def _chat_key():
    from flask import session
    return f'setup_chat_{session.get("user_id") or "owner"}'


def load_chat():
    try:
        chat = json.loads(_setting(_chat_key()) or '[]')
    except ValueError:
        chat = []
    return chat if isinstance(chat, list) else []


def save_chat(chat):
    from extensions import db
    from models import BusinessSetting
    BusinessSetting.set(_chat_key(), json.dumps(chat[-MAX_KEPT:]))
    db.session.commit()


def clear_chat():
    from extensions import db
    from models import BusinessSetting
    BusinessSetting.set(_chat_key(), '')
    db.session.commit()


def api_key():
    import llm
    if not llm.ai_enabled():
        return ''
    return (os.environ.get('ANTHROPIC_API_KEY') or '').strip()


def configured():
    """Whether the chat is shown at all."""
    import demo_guard
    if demo_guard.active():
        return False
    return bool(api_key())


# ---------------------------------------------------------------------------
# What Nana says without asking the model
# ---------------------------------------------------------------------------
#
# The opening line and the line after every Save are written here, not by the
# model. They are the same every time, they cost nothing, and they are the
# lines a person reads most.

# Short on purpose. Every one of these used to lead with why the step
# mattered before asking anything, which is backwards for a conversation: ask,
# and explain only if somebody hesitates. The old six ran to 217 words before
# the owner had answered a single question.
STEP_PROMPTS = {
    'business': lambda has_data: (
        'Quick check — fix anything that’s off, then Save.' if has_data else
        'Fill in the details your customers see, then Save.'),
    'pricing': 'What do you charge for a standard clean of a 2-bed, 2-bath?',
    'terms': 'Your customer terms are ready. Have a look and accept them.',
    'balance': 'When a job’s finished, should the rest come off the card on file?',
    'team': 'Next, you. Check your details and tap Save.',
    'payments': ('Last step: connect payments, so you’re ready to be paid before '
                 'your first customer books. It takes a few minutes and your bank '
                 'details stay with you. No bank details to hand? Skip it for '
                 'tonight and it will be first on your list tomorrow.'),
    'booking_page': 'Want to put your booking page where customers can find it?',
    'client': 'Add a customer you already clean for?',
    'job': 'Book a job and send it to a cleaner — that’s the whole loop.',
}

STEP_LINKS = {
    'business': ('Open my details', '/settings/business'),
    'timezone': ('Set my timezone', '/settings/business'),
    'terms': ('Read my terms', '/settings/business'),
    'payments': ('Connect payments', '/settings/connections'),
    'balance': ('Choose how balances are paid', '/settings/automations'),
    'booking_page': ('Open my booking page', '/settings/booking-page'),
    'job': ('Book a job', '/bookings/new'),
}

# Payments used to live here, as "one more thing worth doing" after setup
# was declared finished -- which read as optional, and is the one thing
# standing between a booking and being paid for it. It is a required step
# now, so by the time this is said it is already done.
DONE_PROMPT = 'That\'s you set up. Anything else is yours to add when you have it.'
DONE_LINK = ('Open my calendar', '/bookings/calendar')


# Steps the owner chose to skip in the chat. Only the chat's order uses
# this: the getting-started list still shows every unfinished step, so
# skipping is "not now", never "pretend it is done".
SKIPPED_KEY = 'setup_chat_skipped'


def skipped():
    return [k for k in _setting(SKIPPED_KEY).split(',') if k]


def skip(step_key):
    from extensions import db
    from models import BusinessSetting
    keys = skipped()
    if step_key and step_key not in keys:
        keys.append(step_key)
    BusinessSetting.set(SKIPPED_KEY, ','.join(keys))
    db.session.commit()


def _next_step():
    """The first unfinished step the owner has not skipped.

    Once every unfinished step has been skipped, the skips are forgotten and
    it starts again from the first unfinished one -- a chat that has run out
    of things to say while setup is still incomplete is a dead end.
    """
    import onboarding
    steps = [s for s in onboarding.progress()['steps'] if not s['done']]
    if not steps:
        return None
    gone = set(skipped())
    for st in steps:
        if st['key'] not in gone:
            return st
    try:
        from extensions import db
        from models import BusinessSetting
        BusinessSetting.set(SKIPPED_KEY, '')
        db.session.commit()
    except Exception:
        pass
    return steps[0]


def next_message(done_line=''):
    """The chat's next turn: what to say, its buttons, and which step it is about.

    Every step that is not finished gets a "Skip for now" button, so nobody is
    stuck on a step they cannot or will not do today.
    """
    step = _next_step()
    if step is None:
        return ((done_line + ' ' + DONE_PROMPT).strip(),
                [_link_card(*DONE_LINK)], 'done')
    cards = []
    # The card comes with the question, already filled in, built here rather
    # than by the model. Three reasons: it is instant, it costs nothing, and
    # the model cannot get a phone number slightly wrong on the way through.
    try:
        builder = _STEP_CARDS.get(step['key'])
        if builder:
            built = builder()
            if isinstance(built, list):
                cards.extend(c for c in built if c)
            else:
                _lines, card = built
                if card:
                    cards.append(card)
    except Exception:
        assistant._record(f'setup card for {step["key"]} could not be built')
    # Chosen after the cards, because for some steps the question is not the
    # same when there is nothing on screen to point at.
    text = STEP_PROMPTS.get(step['key'], step.get('why') or '')
    if callable(text):
        # The business prompt reads differently with boxes already filled in
        # than with blank ones to complete.
        text = text(any(c.get('prefilled') for c in cards))
    # The payments step is the last of the four required ones, and its own
    # wording opens with "Last step", so a generic "That step is done." in
    # front of it is the same news twice. Drop the prefix here only.
    if step.get('key') == 'payments':
        done_line = ''
    # A choice card asks its own question, in the card. Saying it again in a
    # bubble above is the same words twice.
    if any(c.get('kind') == 'choice' for c in cards):
        text = ''
    link = STEP_LINKS.get(step['key'])
    if link and not cards:
        cards.append(_link_card(*link))
    # "Step 2 of 4": counted over the REQUIRED steps only, the same four the
    # progress meter counts, so the card and the meter never disagree. The
    # go-live checks and extras that come after (terms, balance, booking
    # page...) get no
    # number -- they are not step five of four, they are what's left to do once
    # setup is already finished.
    try:
        import onboarding
        required = [s for s in onboarding.progress()['steps'] if s.get('required')]
        total = len(required)
        no = next((i + 1 for i, s in enumerate(required)
                   if s['key'] == step['key']), None)
        if no:
            for c in cards:
                if c.get('kind') in ('form', 'confirm', 'choice', 'team'):
                    c['step_no'], c['step_total'] = no, total
    except Exception:
        pass
    cards.append({'kind': 'skip', 'label': 'Skip for now', 'step': step['key']})
    return (done_line + ' ' + text).strip(), cards, step['key']


# Which step arrives with its own card. Everything not here is a question
# the model answers, or a page the owner has to go to.
_STEP_CARDS = {
    'business': lambda: prefilled_business_card(),
    'team': lambda: team_card(),
    'pricing': lambda: price_card(),
    'terms': lambda: terms_card(),
    'balance': lambda: balance_cards(),
}


def nudge():
    """What to say next, and a button if the step lives on another page."""
    text, cards, _key = next_message()
    links = [c for c in cards if c.get('kind') == 'link']
    return text, (links[0] if links else None)


def greeting():
    opener = (f'Hi, I\'m {NAME}. I\'ll get you set up in a few minutes, one '
              f'question at a time. You can type your answers, ask me anything '
              f'about how Akye works, or skip a step.')
    if _next_step() is None:
        opener = f'Hi, I\'m {NAME}. You\'re all set up.'
    text, cards, key = next_message()
    return f'{opener}\n\n{text}', cards, key


def _link_card(label, href):
    return {'kind': 'link', 'label': label, 'href': href}


# ---------------------------------------------------------------------------
# Tools: three that read, four that offer, one that points
# ---------------------------------------------------------------------------

def _setting(key):
    from models import BusinessSetting
    return (BusinessSetting.get(key) or '').strip()


def tool_progress():
    import onboarding
    p = onboarding.progress()
    lines = [f'{p["done"]} of {p["total"]} setup steps done.']
    for s in p['steps']:
        lines.append(f'- [{"x" if s["done"] else " "}] {s["key"]}: {s["title"]}')
    nxt = p.get('next')
    lines.append(f'Next step: {nxt["key"]}' if nxt else 'All steps are done.')
    return '\n'.join(lines), None


BUSINESS_FIELDS = ('business_name', 'phone', 'email', 'address', 'city',
                   'state', 'zip_code', 'website', 'google_review_link')

FIELD_LABELS = {
    'business_name': 'Business name', 'phone': 'Phone', 'email': 'Email',
    'address': 'Street address', 'city': 'City', 'state': 'State',
    'zip_code': 'ZIP', 'website': 'Website',
    'google_review_link': 'Google review link',
}


def tool_business():
    out = []
    for f in BUSINESS_FIELDS:
        out.append(f'{FIELD_LABELS[f]}: {_setting(f) or "(not set)"}')
    return '\n'.join(out), None


def tool_prices():
    import pricing
    m = pricing.current_matrix()
    reviewed = bool(_setting('pricing_reviewed'))
    lines = ['Standard clean prices on file'
             + (' (the owner has reviewed these)' if reviewed
                else ' (still the starting defaults, not reviewed yet)') + ':']
    for (beds, baths), price in sorted(m.items()):
        lines.append(f'{beds} bed / {baths} bath: ${price:,.0f}')
    return '\n'.join(lines), None


_PHONE_DIGITS = re.compile(r'\d')


def _clean(v, n=300):
    return (str(v or '')).strip()[:n]


def _phone_ok(v):
    return 10 <= len(_PHONE_DIGITS.findall(v or '')) <= 15


def _email_ok(v):
    from notifications import looks_like_email
    return looks_like_email(v)


# The database columns these land in. A value longer than its column fails on
# Postgres after the card's token is spent, so it is refused before the card.
CLIENT_LIMITS = {'name': 100, 'phone': 20, 'email': 120, 'address': 200,
                 'city': 50, 'zip_code': 10}
STAFF_LIMITS = {'name': 100, 'phone': 20, 'email': 120}


def _too_long(vals, limits):
    for k, cap in limits.items():
        if len(vals.get(k) or '') > cap:
            return f'Not offered: the {k.replace("_", " ")} is too long (max {cap} characters).'
    return ''


def _offer(action, payload, title, lines, label):
    import proposals
    from flask import session
    token = proposals.offer(action, payload, summary=title + ': ' + '; '.join(lines),
                            label=label, reversible=True,
                            asked_by=session.get('user_name') or session.get('role'))
    return {'kind': 'confirm', 'token': token, 'title': title,
            'lines': lines, 'label': label}


def _known():
    """What we already hold about this business, without asking anybody."""
    from models import BusinessSetting
    return {f: (BusinessSetting.get(f) or '').strip() for f in BUSINESS_FIELDS}


def _validate_business(kw):
    """Clean and check business fields. Returns (payload, lines, problems).

    The same rules whether the model offered the card or the owner typed into
    an editable one: a bad phone or half an email is refused before anything
    is written, so the form cannot slip a wrong value past on the way in.
    """
    payload, lines, problems = {}, [], []
    for f in BUSINESS_FIELDS:
        v = _clean(kw.get(f))
        if not v:
            continue
        if f == 'phone' and not _phone_ok(v):
            problems.append(f'"{v}" does not look like a full phone number')
            continue
        if f == 'email':
            v = v.lower()
            if not _email_ok(v):
                problems.append(f'"{v}" does not look like a complete email address')
                continue
        if f in ('website', 'google_review_link') and not v.startswith(('http://', 'https://')):
            v = 'https://' + v
        if f == 'state':
            v = v.upper()[:2] if len(v) <= 3 else v
        payload[f] = v
        lines.append(f'{FIELD_LABELS[f]}: {v}')
    return payload, lines, problems


def _form_field(name, value='', *, label=None, kind='text', placeholder='',
                optional=False, prefix=''):
    """One editable box on a form card."""
    return {'name': name,
            'label': label or FIELD_LABELS.get(name, name.replace('_', ' ').title()),
            'value': '' if value is None else str(value),
            'type': kind, 'placeholder': placeholder,
            'optional': bool(optional), 'prefix': prefix}


def _form_card(step, title, fields, label, note='', lines=None):
    """An editable card. Unlike a confirm card it carries no token: the owner
    may change the boxes, so what is written is what was typed, checked again
    on the server by save_form() -- never replayed from a fixed payload."""
    return {'kind': 'form', 'step': step, 'title': title, 'note': note,
            'fields': [f for f in fields if f], 'label': label,
            'lines': lines or []}


def prefilled_business_card():
    """The first card, editable, built before a word is typed. (lines, card).

    Signup gave a name, an email and a ZIP; the ZIP gave the timezone; Google
    often gives the phone and address for a business old enough to be listed.
    All of it goes on the card as boxes the owner can confirm or correct in
    place -- usually one tap on Save, sometimes a phone typed in.

    A business too new to be listed gets the same card with the boxes empty,
    never a dead end that asks nothing and offers nowhere to answer.
    """
    import business_lookup
    import zip_zones
    from models import BusinessSetting
    have = _known()
    name = have.get('business_name') or ''
    found = business_lookup.find(name, have.get('zip_code'))

    def val(f):
        return have.get(f) or found.get(f) or ''

    # A short read-only summary above the boxes: the name, and the timezone
    # the ZIP worked out (not a box, because the ZIP decides it, not a guess).
    lines = []
    if name:
        lines.append(f'{FIELD_LABELS["business_name"]}: {name}')
    zone = (BusinessSetting.get('timezone') or '').strip()
    if zone:
        lines.append(f'Timezone: {zip_zones.label(zone)}')

    fields = [
        _form_field('business_name', name),
        _form_field('phone', val('phone'), kind='tel', placeholder='(555) 123-4567'),
        _form_field('address', val('address'), placeholder='Street address'),
        _form_field('city', val('city')),
        _form_field('state', val('state'), placeholder='FL'),
        _form_field('website', val('website'), optional=True, placeholder='optional'),
    ]
    card = _form_card('business', 'Your details', fields, 'Save & continue',
                      note='The details your customers see.', lines=lines)
    card['prefilled'] = any(f['value'] for f in fields)
    return lines, card


def price_card():
    """The 2-bed / 2-bath price, editable, with the rest worked out from it.
    (lines, card).

    The matrix ships with working numbers, so the box is never blank -- it is
    somebody else's price, already being quoted to real customers, waiting to
    be confirmed or corrected. One tap if it is close; type over it if not.
    """
    import pricing
    try:
        anchor = float(pricing.get_std_price(2, 2) or 0)
    except Exception:
        anchor = 0.0
    if not anchor:
        anchor = float(pricing.PRICE_MATRIX_DEFAULTS.get((2, 2), 225))
    lines = [f'2-bed, 2-bath standard clean: ${anchor:.0f}',
             'Every other size is worked out from this one.']
    fields = [_form_field('two_bed_two_bath', f'{anchor:.0f}', kind='number',
                          label='2-bed, 2-bath standard clean', prefix='$')]
    # Honest about where the number comes from: it is the same starting price
    # everywhere, NOT worked out from her ZIP -- an owner in an expensive city
    # must not take it as local advice.
    card = _form_card('pricing', 'Your prices', fields, 'Save prices',
                      note='A typical starting price for a 2-bed, 2-bath standard '
                           'clean — change it to what you charge. Every other size '
                           'is filled in from it, and you can edit any of them '
                           'later under Pricing.',
                      lines=lines)
    card['prefilled'] = True
    return lines, card


def _owner_name():
    from flask import session
    from models import User
    uid = session.get('user_id')
    u = User.query.get(uid) if uid else None
    return ((u.name if u else '') or session.get('user_name') or '').strip()


def team_card():
    """Step 2: the owner, already filled in, and room for anyone she has.

    One card, not one per cleaner. The owner's own row arrives filled in from
    her login and the details she just saved, with "I clean jobs myself"
    ticked -- a solo owner taps Save and is done. Unticked, the same card is
    a company adding the team it already has, typed or uploaded. Nothing
    here emails anybody: inviting is done from each cleaner's page on the
    Team tab, when the owner has told them (decided 2026-10-24 -- an invite
    card in the middle of setup read as out of place).
    """
    me = {'name': _owner_name(), 'phone': _setting('phone'),
          'email': _setting('email'), 'cleans': True}
    # Just her, on purpose. Pay, other cleaners and spreadsheets all moved to
    # the Team page (2026-10-24): each was a question a brand-new owner might
    # not be able to answer yet, and any one of them is where people walk away.
    card = {'kind': 'team', 'step': 'team', 'title': 'Your team',
            'note': 'Start with you. Already have cleaners? You can add them, or '
                    'upload your list, on the Team page once setup is done.',
            'me': me, 'label': 'Save',
            'team_link': {'label': 'I don’t clean jobs myself — add my cleaners',
                          'href': '/migration/team'}}
    card['prefilled'] = bool(me['name'])
    return [card]


_EMAIL_IN = re.compile(r'[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+')


def _parse_team_paste(text):
    """Rows out of a pasted list: one person per line, in any order of name,
    email and phone, split by commas, tabs or semicolons. Whatever is not an
    email or a phone number is the name."""
    rows = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        email = ''
        m = _EMAIL_IN.search(line)
        if m:
            email = m.group(0)
            line = line.replace(email, ' ')
        name_bits, phone = [], ''
        for part in re.split(r'[,\t;]', line):
            part = part.strip()
            if not part:
                continue
            if not phone and _phone_ok(part) and not re.search(r'[A-Za-z]', part):
                phone = part
            else:
                name_bits.append(part)
        rows.append({'name': ' '.join(name_bits), 'email': email, 'phone': phone})
    return rows


# Column headings people actually use, lowercased with the spaces taken out.
_TEAM_COLUMNS = {
    'name': ('name', 'fullname', 'cleaner', 'cleanername', 'employee',
             'employeename', 'teammember', 'staff', 'contractor'),
    'first': ('first', 'firstname', 'givenname'),
    'last': ('last', 'lastname', 'surname', 'familyname'),
    'email': ('email', 'e-mail', 'emailaddress', 'mail'),
    'phone': ('phone', 'cell', 'mobile', 'phonenumber', 'cellphone', 'cellnumber',
              'mobilenumber', 'tel', 'telephone'),
    'pay': ('pay', 'payrate', 'rate', 'wage', 'hourlyrate', 'hourlypay', 'payperhour',
            'percent', 'commission', 'split', 'pay%', 'percentofjob'),
}
TEAM_FILE_MAX_ROWS = 50


def read_team_file(filename, data, max_rows=TEAM_FILE_MAX_ROWS):
    """Cleaners out of an uploaded CSV or Excel file. (rows, error).

    Saves nothing: the rows go back onto the team card for the owner to see,
    and the card's Save checks them like any typed row. With a heading row
    the columns are matched by name (Name, or First + Last; Email; Phone,
    Cell or Mobile). Without one, each row is read the way a pasted line is.
    """
    import csv
    import io
    name = (filename or '').lower()
    if len(data or b'') > 2_000_000:
        return None, 'That file is too big. Keep it under 2 MB.'
    if name.endswith('.xls'):
        return None, ('That is an old Excel file. Open it and save it as .xlsx '
                      'or CSV, then upload it again.')
    table = []
    try:
        if name.endswith(('.xlsx', '.xlsm')):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            for row in wb.worksheets[0].iter_rows(values_only=True):
                table.append(['' if v is None else str(v).strip() for v in row])
                if len(table) > 1000:
                    break
        elif name.endswith(('.csv', '.txt')):
            text = data.decode('utf-8-sig', errors='replace')
            table = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))][:1001]
        else:
            return None, 'Upload an Excel (.xlsx) or CSV file.'
    except Exception:
        return None, ('That file could not be read. Save it as .xlsx or CSV and '
                      'try again.')
    table = [r for r in table if any(r)]
    if not table:
        return None, 'That file is empty.'
    head = [re.sub(r'[\s_]+', '', c.lower()) for c in table[0]]
    cols = {}
    for key, names in _TEAM_COLUMNS.items():
        for i, h in enumerate(head):
            if h in names and key not in cols:
                cols[key] = i
    rows = []
    if 'email' in cols or 'name' in cols or 'first' in cols:
        def cell(r, k):
            i = cols.get(k)
            return r[i].strip() if i is not None and i < len(r) else ''
        for r in table[1:]:
            nm = cell(r, 'name') or ' '.join(x for x in (cell(r, 'first'), cell(r, 'last')) if x)
            row = {'name': nm, 'email': cell(r, 'email'), 'phone': cell(r, 'phone')}
            if any(row.values()):
                # Pay comes over only when the sheet says it plainly: a "%"
                # or a percent-style heading is a share of the job, a "$" or
                # an hourly heading is hourly. Anything else is left for the
                # owner to fill in, never guessed.
                raw = cell(r, 'pay')
                h = head[cols['pay']] if 'pay' in cols else ''
                row['pay_rate'] = re.sub(r'[^\d.]', '', raw)
                row['pay_type'] = ('percent' if '%' in raw or h in ('percent', 'commission', 'split', 'pay%', 'percentofjob')
                                   else 'hourly' if '$' in raw or 'hour' in h or h == 'wage'
                                   else '')
                if not row['pay_type'] or not row['pay_rate']:
                    row['pay_type'], row['pay_rate'] = '', ''
                rows.append(row)
    else:
        rows = _parse_team_paste('\n'.join(', '.join(c for c in r if c) for r in table))
    if not rows:
        return None, 'No cleaners found in that file — it needs a name on each row.'
    if len(rows) > max_rows:
        return None, (f'That file has {len(rows)} people. Upload up to '
                      f'{max_rows} at a time.')
    return rows, None


PAY_TYPES = {'percent': '% of the job', 'hourly': '$ per hour'}


def _pay(row):
    """(pay_type, rate, problem) for one person being added.

    A blank box used to become the model's default -- half of every job --
    which is somebody else's pay scale, quietly written into payroll. So
    blank stays blank: rate None, shown as "Pay not set" until the owner
    sets it. Given, it is checked. 0 is allowed."""
    kind = (row.get('pay_type') or '').strip().lower()
    text = str(row.get('pay_rate') or '').strip().replace('%', '').replace('$', '').replace(',', '')
    who = row.get('name') or 'Someone'
    # Not given is allowed, and saved as "not set" -- never as a default.
    # Pay is decided on the Team page, not in the first five minutes of
    # setup, where it was a question a brand-new owner cannot answer yet.
    if not kind and not text:
        return 'percent', None, ''
    if kind not in PAY_TYPES:
        return None, None, f'{who} needs a pay type (% of the job or $ per hour)'
    if not text:
        return None, None, f'{who} needs a pay rate'
    try:
        rate = round(float(text), 2)
    except ValueError:
        return None, None, f'{who}’s pay "{text}" is not a number'
    cap = 100 if kind == 'percent' else 500
    if not 0 <= rate <= cap:
        return None, None, (f'{who}’s pay looks off — use 0 to 100 for % of the job'
                            if kind == 'percent' else
                            f'{who}’s pay looks off — use $0 to $500 an hour')
    return kind, rate, ''


def _team_rows(fields):
    """The people on a submitted team card, owner first. (rows, problems).

    Every row is checked before any is written, so a card with one bad email
    saves nobody rather than half a team -- fixing the one box and pressing
    Save again must not then trip over the people the first press added."""
    from blueprints.staff import _name_taken
    rows, problems = [], []
    if str(fields.get('me_cleans') or '') in ('1', 'true', 'on', 'yes'):
        rows.append({'name': _clean(fields.get('me_name')),
                     'phone': _clean(fields.get('me_phone')),
                     'email': _clean(fields.get('me_email')).lower(), 'me': True,
                     'pay_type': _clean(fields.get('me_pay_type'), 20),
                     'pay_rate': _clean(fields.get('me_pay_rate'), 20)})
    others = fields.get('others')
    for o in (others if isinstance(others, list) else [])[:50]:
        if isinstance(o, dict):
            rows.append({'name': _clean(o.get('name')), 'phone': _clean(o.get('phone')),
                         'email': _clean(o.get('email')).lower(),
                         'pay_type': _clean(o.get('pay_type'), 20),
                         'pay_rate': _clean(o.get('pay_rate'), 20)})
    for o in _parse_team_paste(str(fields.get('paste') or '')[:5000]):
        rows.append({'name': _clean(o['name']), 'phone': _clean(o['phone']),
                     'email': _clean(o['email']).lower(),
                     'pay_type': _clean(fields.get('paste_pay_type'), 20),
                     'pay_rate': _clean(fields.get('paste_pay_rate'), 20)})
    # A row with nothing in it is an empty box, not a person.
    rows = [r for r in rows if r['name'] or r['phone'] or r['email']]
    seen = set()
    for r in rows:
        who = r['name'] or r['email'] or r['phone']
        if not r['name']:
            problems.append(f'{who} needs a name')
            continue
        long = _too_long(r, STAFF_LIMITS)
        if long:
            problems.append(f'{r["name"]}: ' + long.replace('Not offered: ', ''))
        if r['phone'] and not _phone_ok(r['phone']):
            problems.append(f'{r["name"]}’s phone "{r["phone"]}" is not a full number')
        if r['email'] and not _email_ok(r['email']):
            problems.append(f'{r["name"]}’s email "{r["email"]}" is not complete')
        r['pay_type'], r['pay_rate'], pay_problem = _pay(r)
        if pay_problem:
            problems.append(pay_problem)
        # Names must be distinct: a solo job pays the cleaner it names, and
        # two Marias share one pay history (blueprints/staff._name_taken).
        key = r['name'].lower()
        if key in seen:
            problems.append(f'{r["name"]} is on the list twice — add a surname or initial')
        elif _name_taken(r['name']):
            problems.append(f'you already have a team member called {r["name"]}')
        seen.add(key)
    return rows, problems


def save_team(fields):
    """Write the team card: every row, or none of them."""
    import entitlements
    from flask import session
    from extensions import db
    from models import Staff, User
    rows, problems = _team_rows(fields or {})
    if problems:
        return False, 'Please check: ' + '; '.join(problems) + '.'
    if not rows:
        return False, ('Add at least one cleaner, or tick “I clean jobs myself” '
                       'if it’s you for now.')
    left = entitlements.remaining('field_workers')
    if left is not None and len(rows) > left:
        _ok, why = entitlements.check_limit('field_workers')
        room = f'{left} more cleaner{"" if left == 1 else "s"}'
        return False, (why or f'Your plan has room for {room}.') + (
            f' This card has {len(rows)}.')
    added = []
    for r in rows:
        # sa.null(), not None: a plain None lets the ORM fall back to the
        # column default -- 50% -- which is exactly what "not set" must not be.
        import sqlalchemy as sa
        s = Staff(name=r['name'], phone=r['phone'], email=r['email'], is_active=True,
                  pay_type=r['pay_type'],
                  pay_rate=sa.null() if r['pay_rate'] is None else r['pay_rate'])
        # Brought over, not hired: their checklist is the paperwork only.
        s.mark_existing_team(owner=bool(r.get('me')))
        if r.get('me'):
            # Her own login, linked from the start, so she never gets a
            # "join the team" email from her own business.
            uid = session.get('user_id')
            if uid and User.query.get(uid) and not Staff.query.filter_by(user_id=uid).first():
                s.user_id = uid
        db.session.add(s)
        added.append(r['name'] + (' (you)' if r.get('me') else ''))
    db.session.commit()
    said = f'Your team: {", ".join(added)}.'
    if any(not r.get('me') for r in rows):
        said += ' Nobody was emailed — invite them from the Team tab when you’re ready.'
    return True, said


def terms_card():
    """The terms, as four lines rather than thirteen hundred words."""
    lines = ['Payment is due when the job is done',
             'Cancellations: 24 hours’ notice',
             'Somebody must be able to let the cleaner in',
             'Not happy? Tell us within 24 hours and we put it right']
    card = _offer('setup_accept_terms', {'accepted': '1'},
                  'Your customer terms', lines, 'Accept these')
    # Most owners accept the sensible draft in one tap. The few who want to
    # change a line need somewhere to go that is not the chat box -- a quiet
    # link under the button, to the terms editor on the business page.
    card['secondary'] = {'label': 'Prefer to change them? Edit your terms',
                         'href': '/settings/business'}
    return lines, card


def balance_cards():
    """One card: the question, and its two answers side by side.

    This used to be two cards, each titled "How balances get paid" with one
    button, under a chat bubble asking the question. Owners read that as two
    separate steps -- both said "Step 4 of 4" -- when it is one question with
    a yes and a no. Each answer still carries its own token, so whichever is
    tapped saves exactly what it said.
    """
    options = []
    for mode, label, line in (
            ('auto', 'Yes — charge the card',
             'The rest comes off the card on file when the job is done'),
            ('ask', 'No — I’ll decide each time',
             'The balance shows as owed, and waits for you')):
        offered = _offer('setup_set_balance_mode', {'mode': mode},
                         'How balances get paid', [line], label)
        options.append({'token': offered['token'], 'label': label, 'line': line})
    return [{'kind': 'choice', 'title': STEP_PROMPTS['balance'],
             'options': options}]


def tool_offer_business(**kw):
    payload, lines, problems = _validate_business(kw)
    if problems:
        return ('Not offered. Ask them to check: ' + '; '.join(problems) + '.'), None
    if not payload:
        return 'Not offered: there was nothing to save.', None
    card = _offer('setup_save_business', payload, 'Save your business details',
                  lines, 'Save details')
    return ('A card is on screen with these details and a Save button. '
            'Nothing is saved until they press it.'), card


# The timezones a US cleaning business is actually in. A free-text zone name
# from a model is a silent wrong answer waiting to happen -- ZoneInfo accepts
# plenty of names nobody means -- so the card can only offer one of these.
TIMEZONES = {
    'eastern': ('America/New_York', 'Eastern'),
    'central': ('America/Chicago', 'Central'),
    'mountain': ('America/Denver', 'Mountain'),
    'arizona': ('America/Phoenix', 'Arizona (no daylight saving)'),
    'pacific': ('America/Los_Angeles', 'Pacific'),
    'alaska': ('America/Anchorage', 'Alaska'),
    'hawaii': ('Pacific/Honolulu', 'Hawaii'),
    'atlantic': ('America/Puerto_Rico', 'Atlantic (Puerto Rico, Virgin Islands)'),
    'puerto rico': ('America/Puerto_Rico', 'Atlantic (Puerto Rico, Virgin Islands)'),
    'virgin islands': ('America/Puerto_Rico', 'Atlantic (Puerto Rico, Virgin Islands)'),
    'chamorro': ('Pacific/Guam', 'Chamorro (Guam)'),
    'guam': ('Pacific/Guam', 'Chamorro (Guam)'),
}


def tool_offer_timezone(zone=''):
    """Show a card setting the timezone everything is scheduled against."""
    want = (zone or '').strip().lower()
    # A zone's own name first: 'Pacific/Honolulu' starts with 'pacific' and
    # would otherwise be offered Los Angeles.
    found = next(((name, label) for name, label in TIMEZONES.values()
                  if want == name.lower()), None)
    for key, (name, label) in TIMEZONES.items():
        if not found and (want == key or want.startswith(key)):
            found = (name, label)
    if not found:
        return ('Not offered: ask which of these they are in — Eastern, Central, '
                'Mountain, Arizona, Pacific, Alaska, Hawaii, Atlantic (Puerto Rico, '
                'Virgin Islands) or Chamorro (Guam).'), None
    name, label = found
    card = _offer('setup_set_timezone', {'timezone': name},
                  'Set your timezone', [f'Timezone: {label} ({name})'],
                  'Set timezone')
    return ('A card is on screen with that timezone and a button. Nothing '
            'changes until they press it.'), card


BALANCE_CHOICES = {
    'auto': ('auto', 'Charge the card on file when the job is done'),
    'ask': ('ask', 'Leave it owed, and you decide each time'),
    'never': ('never', 'Never charge here — collected some other way'),
}


def tool_offer_balance_mode(choice=''):
    """Show a card recording how balances get collected."""
    want = (choice or '').strip().lower()
    key = None
    for k in BALANCE_CHOICES:
        if want == k or want.startswith(k):
            key = k
            break
    if key is None:
        if want in ('automatic', 'automatically', 'card', 'charge'):
            key = 'auto'
        elif want in ('manual', 'me', 'myself', 'decide'):
            key = 'ask'
    if key is None:
        return ('Not offered: ask whether the balance should come off the card '
                'automatically, wait for them to say so, or never be taken here.'), None
    mode, label = BALANCE_CHOICES[key]
    card = _offer('setup_set_balance_mode', {'mode': mode},
                  'How balances get paid', [label], 'Save this choice')
    return ('A card is on screen with that choice and a button. Nothing '
            'changes until they press it.'), card


def tool_offer_prices(two_bed_two_bath_price=''):
    import pricing
    try:
        anchor = float(re.sub(r'[^\d.]', '', str(two_bed_two_bath_price)) or 0)
    except ValueError:
        anchor = 0
    if not 40 <= anchor <= 2000:
        return ('Not offered: that price looks wrong for a 2 bed / 2 bath '
                'standard clean. Ask again.'), None
    matrix = pricing.suggest_matrix(anchor)
    matrix[(2, 2)] = round(anchor, 2)
    payload = {f'{b}_{ba}': v for (b, ba), v in matrix.items()}
    shown = [(1, 1), (2, 2), (3, 2), (4, 3)]
    lines = [f'{b} bed / {ba} bath: ${matrix[(b, ba)]:,.0f}' for b, ba in shown
             if (b, ba) in matrix]
    lines.append('Other sizes scaled the same way. Every price stays editable.')
    card = _offer('setup_set_prices', payload, 'Set your standard clean prices',
                  lines, 'Use these prices')
    return ('A card is on screen with the suggested price list and a button. '
            'The 2/2 price is theirs; the other sizes are scaled from it. '
            'Nothing is saved until they press it.'), card


def tool_offer_cleaner(name='', phone='', email=''):
    from blueprints.staff import _name_taken
    name, phone, email = _clean(name), _clean(phone), _clean(email).lower()
    if not name:
        return 'Not offered: a cleaner needs a name.', None
    long = _too_long({'name': name, 'phone': phone, 'email': email}, STAFF_LIMITS)
    if long:
        return long, None
    if phone and not _phone_ok(phone):
        return f'Not offered: "{phone}" does not look like a full phone number.', None
    if email and not _email_ok(email):
        return f'Not offered: "{email}" does not look like a complete email.', None
    clash = _name_taken(name)
    if clash:
        return (f'Not offered: there is already a team member called {clash.name}. '
                f'Ask for a surname or initial to tell them apart.'), None
    lines = [f'Name: {name}']
    if phone:
        lines.append(f'Cell: {phone}')
    if email:
        lines.append(f'Email: {email}')
    if not phone:
        lines.append('No cell number, so job offers will go by email.')
    card = _offer('setup_add_cleaner', {'name': name, 'phone': phone, 'email': email},
                  'Add a cleaner to your team', lines, 'Add cleaner')
    return ('A card is on screen with this cleaner and an Add button. '
            'Nothing is saved until they press it.'), card


def tool_offer_customer(name='', phone='', email='', address='', city='', zip_code=''):
    vals = {'name': _clean(name, 300), 'phone': _clean(phone, 300),
            'email': _clean(email, 300).lower(), 'address': _clean(address, 300),
            'city': _clean(city, 300), 'zip_code': _clean(zip_code, 300)}
    if not vals['name']:
        return 'Not offered: a customer needs a name.', None
    long = _too_long(vals, CLIENT_LIMITS)
    if long:
        return long, None
    if vals['phone'] and not _phone_ok(vals['phone']):
        return f'Not offered: "{vals["phone"]}" does not look like a full phone number.', None
    if vals['email'] and not _email_ok(vals['email']):
        return f'Not offered: "{vals["email"]}" does not look like a complete email.', None
    labels = (('name', 'Name'), ('phone', 'Phone'), ('email', 'Email'),
              ('address', 'Address'), ('city', 'City'), ('zip_code', 'ZIP'))
    lines = [f'{lab}: {vals[k]}' for k, lab in labels if vals[k]]
    card = _offer('setup_add_customer', vals, 'Add a customer', lines, 'Add customer')
    return ('A card is on screen with this customer and an Add button. '
            'Nothing is saved until they press it.'), card


PAGES = {
    'booking_page': ('Open my booking page', '/settings/booking-page'),
    'book_job': ('Book a job', '/bookings/new'),
    'prices': ('Edit all my prices', '/settings/pricing'),
    'business_settings': ('Business settings', '/settings/business'),
    'payments': ('Connect payments', '/settings/connections'),
    'import': ('Import my team or customers', '/migration'),
    'hiring': ('Hiring settings', '/contractors/hiring-settings'),
}


def tool_show_page(page=''):
    if page not in PAGES:
        return 'No such page. Choose one of: ' + ', '.join(PAGES), None
    return f'A button to "{PAGES[page][0]}" is on screen.', _link_card(*PAGES[page])


def tool_how_to(question=''):
    import help_guide
    text, link = help_guide.answer(question)
    return text, (_link_card(*link) if link else None)


_S = {'type': 'string'}

TOOLS = {
    'get_setup_progress': (
        tool_progress, 'Which setup steps are done and which is next. Call this '
        'before deciding what to ask about.', {}),
    'get_business_details': (
        tool_business, 'The business details currently saved.', {}),
    'get_prices': (
        tool_prices, 'The standard clean prices currently on file.', {}),
    'offer_business_details': (
        tool_offer_business, 'Show a Save card for business details the owner '
        'just gave you. Only include fields they actually gave.',
        {f: _S for f in BUSINESS_FIELDS}),
    'offer_prices': (
        tool_offer_prices, 'Show a card that sets their whole standard price list '
        'from what they charge for a 2 bed / 2 bath standard clean.',
        {'two_bed_two_bath_price': _S}),
    'offer_timezone': (
        tool_offer_timezone, 'Show a card setting the business timezone, once '
        'the owner has said where they are. Everything is scheduled against it.',
        {'zone': {'type': 'string',
                  'description': 'Eastern, Central, Mountain, Arizona, '
                                 'Pacific, Alaska, Hawaii, Atlantic (Puerto Rico, '
                                 'Virgin Islands) or Chamorro (Guam).'}}),
    'offer_balance_mode': (
        tool_offer_balance_mode, 'Show a card recording how the rest of a job\'s '
        'price is collected once it is finished.',
        {'choice': {'type': 'string',
                    'description': "'auto' to charge the card on file, 'ask' to "
                                   "leave it for the owner to decide, 'never' if "
                                   "they collect it another way."}}),
    'offer_add_cleaner': (
        tool_offer_cleaner, 'Show an Add card for one cleaner the owner named.',
        {'name': _S, 'phone': _S, 'email': _S}),
    'offer_add_customer': (
        tool_offer_customer, 'Show an Add card for one customer the owner named.',
        {'name': _S, 'phone': _S, 'email': _S, 'address': _S, 'city': _S,
         'zip_code': _S}),
    'how_to': (
        tool_how_to, 'Look up how Akye works or how to do something in it '
        '(hiring, onboarding cleaners, payments, the booking page, any feature).',
        {'question': {'type': 'string', 'description': 'Their question, in their words.'}}),
    'show_page': (
        tool_show_page, 'Show a button to a page they need to do something on '
        'themselves. Pages: ' + ', '.join(PAGES) + '.',
        {'page': {'type': 'string', 'enum': list(PAGES)}}),
}


def tool_schema():
    return [{'name': n, 'description': desc,
             'input_schema': {'type': 'object', 'properties': props}}
            for n, (_fn, desc, props) in TOOLS.items()]


def _run_tool(name, args):
    """(text for the model, card or None). Never raises."""
    if name not in TOOLS:
        return 'That is not a tool.', None
    fn, _desc, props = TOOLS[name]
    args = {k: v for k, v in (args or {}).items()
            if k in props and isinstance(v, (str, int, float))}
    args = {k: str(v) for k, v in args.items()}
    try:
        return fn(**args)
    except Exception as e:
        assistant._record(f'setup tool {name} failed: {type(e).__name__}')
        return 'That could not be done just now.', None


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def system_prompt(opening):
    biz = _setting('business_name') or '(name not set yet)'
    return (
        f'You are {NAME}, the setup guide inside Akye, software for cleaning and '
        f'home service businesses. You are helping the owner of "{biz}" set up '
        'their account right after signing up. Be warm, plain and brief: two or '
        'three short sentences, then one question. They may be on a phone.\n\n'

        'THE SETUP STEPS, IN ORDER\n'
        'Required, in this order: business (contact details customers see), '
        'team (the owner herself if she cleans, plus anyone who already cleans '
        'for her; the card on screen takes them all at once), pricing (one '
        'price for a 2 bed / 2 bath standard clean sets the whole list), '
        'payments (the owner connects Stripe herself on the Connections page, '
        'so she is ready to be paid before her first booking). Then, before '
        'going live: terms (accept the customer terms), balance (charge the '
        'rest automatically or not). Then optional: booking_page (share the '
        'self-booking link), client (add one real customer), job (book and '
        'assign a job).\n'
        'Work on the next unfinished step unless they ask about something else. '
        'Ask for one step at a time. If they want to skip, move on.\n\n'

        'HOW SAVING WORKS\n'
        'You never save anything yourself. When they give you details, call the '
        'matching offer_ tool. That puts a card on screen; it is saved only when '
        'they press its button. So never say "saved" or "added". Say something '
        'like "Check the card and tap Save." Only offer what they actually told '
        'you; never invent a phone number, email, price or name. If a tool says '
        'something was not offered, tell them what to fix.\n\n'

        'NEVER\n'
        'Never ask for or accept bank account numbers, card numbers, Social '
        'Security numbers, passwords or API keys. If they offer any, tell them '
        'not to type it here and point them to the right page with show_page. '
        'Never promise features that are not described below.\n\n'

        'QUESTIONS ABOUT HOW AKYE WORKS\n'
        'Call how_to and answer from what it returns, briefly and in plain '
        'words, then come back to the setup step. If it does not cover the '
        'question, say you are not sure and suggest Akye support. Never '
        'describe a feature from memory.\n\n'

        f'Your opening message to them was:\n"{opening}"\n\n'
        'Style: no headings, no lists unless they ask, no exclamation marks.'
    )


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------

def _month_key():
    from datetime import date
    return f'setup_assistant_used_{date.today():%Y-%m}'


def used_this_month():
    try:
        return int(_setting(_month_key()) or 0)
    except ValueError:
        return 0


def remaining():
    return max(0, MONTHLY_LIMIT - used_this_month())


def _count_one():
    """Counted before the call, so a call that times out still counts."""
    from extensions import db
    from models import BusinessSetting
    BusinessSetting.set(_month_key(), str(used_this_month() + 1))
    db.session.commit()


TROUBLE = {
    'off': (f'{NAME} is not available right now. You can keep going with the '
            f'list below.'),
    'limit': (f'{NAME} has answered a lot of questions this month. The list '
              f'below has every step, and each one opens the right page.'),
    'unreachable': 'I could not connect just then. Try again in a moment.',
    'error': 'Something went wrong on my side. Try again, or use the list below.',
}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def _post(body, timeout=20):
    import requests
    r = requests.post(API_URL, timeout=timeout, json=body, headers={
        'x-api-key': api_key(),
        'anthropic-version': API_VERSION,
        'content-type': 'application/json',
    })
    return r.json()


def _api_history(history):
    """Display history -> alternating user/assistant messages, user first."""
    msgs = []
    for m in history or []:
        role, text = m.get('role'), (m.get('content') or '').strip()
        if role not in ('user', 'assistant') or not text:
            continue
        if msgs and msgs[-1]['role'] == role:
            msgs[-1]['content'] += '\n\n' + text
        else:
            msgs.append({'role': role, 'content': text})
    while msgs and msgs[0]['role'] != 'user':
        msgs.pop(0)
    return msgs[-HISTORY_MESSAGES:] if len(msgs) > HISTORY_MESSAGES else msgs


def ask(message, history=None, opening=''):
    """One message from the owner. Returns {'say': str, 'cards': [...]}."""
    if not configured():
        return {'say': TROUBLE['off'], 'cards': []}
    if remaining() <= 0:
        return {'say': TROUBLE['limit'], 'cards': []}
    _count_one()

    messages = _api_history(history)
    if messages and messages[-1]['role'] == 'user':
        messages[-1]['content'] += '\n\n' + message[:1500]
    else:
        messages.append({'role': 'user', 'content': message[:1500]})
    if messages and messages[0]['role'] != 'user':
        messages.insert(0, {'role': 'user', 'content': '(I just signed up.)'})

    system = system_prompt(opening)
    tools = tool_schema()
    cards = []
    said = []          # text from every step: Claude often writes its sentence
                       # alongside the tool call, then says nothing after it
    # Gunicorn kills a request at 60 seconds. Stop well before that.
    import time
    deadline = time.monotonic() + DEADLINE_SECONDS

    def finish():
        if said:
            return {'say': '\n\n'.join(said), 'cards': cards}
        if cards:
            return {'say': 'Check the card below.', 'cards': cards}
        return {'say': TROUBLE['error'], 'cards': cards}

    for _step in range(MAX_STEPS):
        left = deadline - time.monotonic()
        if left < 5:
            break
        try:
            resp = _post({'model': MODEL, 'max_tokens': 1500, 'system': system,
                          'tools': tools, 'messages': messages},
                         timeout=min(20, left))
        except Exception as e:
            assistant._record(f'setup assistant could not reach Claude: {type(e).__name__}')
            if said or cards:
                return finish()
            return {'say': TROUBLE['unreachable'], 'cards': cards}

        if not isinstance(resp, dict) or resp.get('type') == 'error':
            err = resp.get('error') if isinstance(resp, dict) else None
            assistant._record('setup assistant: ' + str((err or {}).get('message', resp))[:200])
            if said or cards:
                return finish()
            return {'say': TROUBLE['error'], 'cards': cards}

        content = resp.get('content') or []
        text = '\n\n'.join((b.get('text') or '').strip() for b in content
                            if b.get('type') == 'text' and (b.get('text') or '').strip())
        if text:
            said.append(text)
        uses = [b for b in content if b.get('type') == 'tool_use']

        # Cut off mid-reply: a tool call written halfway has half its input.
        if resp.get('stop_reason') == 'max_tokens' or not uses:
            if not said and not cards:
                assistant._record(f'setup assistant said nothing '
                                  f'(stop_reason={resp.get("stop_reason")})')
            return finish()

        messages.append({'role': 'assistant', 'content': content})
        results = []
        for i, b in enumerate(uses):
            # Every tool_use needs an answer or the next call is rejected.
            if i >= 4:
                results.append({'type': 'tool_result', 'tool_use_id': b.get('id'),
                                'content': 'Not run: too many at once. Do one thing at a time.',
                                'is_error': True})
                continue
            out, card = _run_tool(b.get('name'), b.get('input'))
            if card:
                cards.append(card)
            results.append({'type': 'tool_result', 'tool_use_id': b.get('id'),
                            'content': out or 'done'})
        messages.append({'role': 'user', 'content': results})

    return finish()


# ---------------------------------------------------------------------------
# What runs when the owner presses a card's button
# ---------------------------------------------------------------------------
#
# Each one checks again. The card was right when it was offered; the world
# can move before the button is pressed.

def _timezone_from_zip():
    """Set the timezone from the ZIP, if we have one and no timezone yet.

    Derived wherever a ZIP turns up, rather than asked. A company that joined
    before the ZIP field existed gets its timezone the moment it tells us
    where it is, without ever being asked a question whose right answer we
    could work out.
    """
    from extensions import db
    from models import BusinessSetting
    import zip_zones
    if (BusinessSetting.get('timezone') or '').strip():
        return
    zone = zip_zones.zone_for_zip(BusinessSetting.get('zip_code'))
    if zone:
        BusinessSetting.set('timezone', zone)
        db.session.commit()


def save_business(payload):
    import demo_guard
    from extensions import db
    from models import BusinessSetting
    if demo_guard.active():
        return False, demo_guard.IDENTITY_DETAIL
    saved = 0
    for f in BUSINESS_FIELDS:
        v = payload.get(f)
        if isinstance(v, str) and v.strip():
            BusinessSetting.set(f, v.strip())
            saved += 1
    if not saved:
        return False, 'There was nothing to save.'
    db.session.commit()
    _timezone_from_zip()
    try:
        import legacy_brands
        legacy_brands.restore_if_original()
    except Exception:
        pass
    return True, 'Business details saved.'


def set_prices(payload):
    import pricing
    from extensions import db
    from models import BusinessSetting
    sizes = set(pricing.matrix_sizes())
    n = 0
    for key, val in (payload or {}).items():
        try:
            beds, baths = (int(x) for x in key.split('_'))
            price = round(float(val), 2)
        except (TypeError, ValueError):
            continue
        if (beds, baths) in sizes and 0 < price < 10000:
            pricing.set_std_price(beds, baths, price)
            n += 1
    if not n:
        return False, 'Those prices could not be saved.'
    BusinessSetting.set('pricing_reviewed', '1')
    db.session.commit()
    return True, 'Prices saved. You can fine-tune any size on the Prices page.'


def save_form(step, fields):
    """Write an editable setup card. The form is only an input; every value is
    checked again here, the same rules the model's offer card goes through, so
    nothing is trusted just because it arrived from a box on the page."""
    import demo_guard
    if demo_guard.active():
        return False, demo_guard.IDENTITY_DETAIL
    fields = fields or {}
    if step == 'business':
        payload, _lines, problems = _validate_business(fields)
        if problems:
            return False, 'Please check: ' + '; '.join(problems) + '.'
        if not payload:
            return False, 'Add at least one detail before saving.'
        return save_business(payload)
    if step == 'team':
        return save_team(fields)
    if step == 'pricing':
        try:
            anchor = float(re.sub(r'[^\d.]', '', str(fields.get('two_bed_two_bath'))) or 0)
        except ValueError:
            anchor = 0
        if not 40 <= anchor <= 2000:
            return False, ('That price looks off for a 2-bed, 2-bath standard '
                           'clean. Try a number between $40 and $2,000.')
        import pricing
        matrix = pricing.suggest_matrix(anchor)
        matrix[(2, 2)] = round(anchor, 2)
        payload = {f'{b}_{ba}': v for (b, ba), v in matrix.items()}
        return set_prices(payload)
    return False, 'That is not something to save here.'


def add_cleaner(payload):
    import entitlements
    from blueprints.staff import _name_taken
    from extensions import db
    from models import Staff
    name = (payload.get('name') or '').strip()
    if not name:
        return False, 'That cleaner had no name.'
    ok, why = entitlements.check_limit('field_workers')
    if not ok:
        return False, why
    if _name_taken(name):
        return False, f'You already have a team member called {name}.'
    s = Staff(name=name, phone=(payload.get('phone') or '').strip(),
              email=(payload.get('email') or '').strip(), is_active=True)
    db.session.add(s)
    db.session.commit()
    return True, f'{s.name} added to your team.'


def add_customer(payload):
    from extensions import db
    from models import Client
    name = (payload.get('name') or '').strip()
    if not name:
        return False, 'That customer had no name.'
    c = Client(name=name,
               email=(payload.get('email') or '').strip().lower(),
               phone=(payload.get('phone') or '').strip(),
               address=(payload.get('address') or '').strip(),
               city=(payload.get('city') or '').strip(),
               zip_code=(payload.get('zip_code') or '').strip())
    db.session.add(c)
    db.session.commit()
    return True, f'{c.name} added to your customers.'


# Its own list, apart from Nana's ACTIONS: a setup card cannot be confirmed
# through the general assistant, and a Nana proposal cannot be confirmed here.
def set_timezone(payload):
    """Write the timezone. Only ever one of TIMEZONES, checked again here."""
    from extensions import db
    from models import BusinessSetting
    name = (payload.get('timezone') or '').strip()
    if name not in {z for z, _l in TIMEZONES.values()}:
        return False, 'That is not a timezone I can set.'
    BusinessSetting.set('timezone', name)
    db.session.commit()
    label = next(l for z, l in TIMEZONES.values() if z == name)
    return True, (f'Timezone set to {label}. Reminders, the day\'s plan and '
                  f'your end-of-day numbers all follow it from now on.')


def set_balance_mode(payload):
    """Record how balances are collected. A choice, not a default."""
    import automations
    from extensions import db
    mode = (payload.get('mode') or '').strip()
    if mode not in {m for m, _l in BALANCE_CHOICES.values()}:
        return False, 'That is not a choice I can save.'
    automations.set_balance_mode(mode)
    db.session.commit()
    return True, {
        'auto': 'Saved. When a job is finished the rest comes off the card on '
                'file — you can change it any time under Automations.',
        'ask': 'Saved. Balances will show as owed and wait for you, rather than '
               'being charged automatically.',
        'never': 'Saved. Nothing will be charged here; balances are yours to '
                 'collect however you do it.',
    }[mode]


def accept_terms(payload):
    """Record that the owner has read and accepted the customer terms.

    The terms themselves already exist and are already in force -- a generic
    draft stands in until a business writes its own, which means a company
    that never finishes setup is trading under terms nobody has read. This is
    the reading happening, not the terms being created.
    """
    from extensions import db
    from models import BusinessSetting
    if str(payload.get('accepted') or '') != '1':
        return False, 'Nothing to accept there.'
    BusinessSetting.set('terms_reviewed', '1')
    db.session.commit()
    return True, ('Terms accepted. Customers agree to them at the moment they '
                  'book, and you can change the wording any time in Settings.')


ACTIONS = {
    'setup_save_business': save_business,
    'setup_accept_terms': accept_terms,
    'setup_set_timezone': set_timezone,
    'setup_set_balance_mode': set_balance_mode,
    'setup_set_prices': set_prices,
    'setup_add_cleaner': add_cleaner,
    'setup_add_customer': add_customer,
}


def confirm(token):
    """Run the card behind a token. Returns (ok, sentence)."""
    import proposals
    from models import AssistantProposal
    token = (token or '').strip()
    row = AssistantProposal.query.filter_by(token=token).first() if token else None
    if row is None or row.action not in ACTIONS:
        return False, 'That card is not something I can save.'
    action, payload, row = proposals.take(token)
    if not action:
        return False, {
            'already-done': 'That one is already saved.',
            'stale': 'That card is too old now. Tell me again and I\'ll make a fresh one.',
        }.get(proposals.why_not(token), 'That card is not something I can save.')
    try:
        ok, said = ACTIONS[action](payload)
    except Exception:
        assistant._record(f'setup action failed: {action}')
        try:
            from extensions import db
            db.session.rollback()
        except Exception:
            pass
        ok, said = False, 'That did not save. It has been recorded.'
    proposals.record(row, ('done: ' if ok else 'refused: ') + said)
    return ok, said
