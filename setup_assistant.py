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
MODEL = os.environ.get('SETUP_ASSISTANT_MODEL', 'claude-haiku-5-5')

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

STEP_PROMPTS = {
    'business': ('Let\'s start with the basics. What phone number and email '
                 'should your customers see? (Your business name too, if it '
                 'isn\'t right yet.)'),
    'pricing': ('Now your prices. What do you charge for a standard clean of a '
                '2-bedroom, 2-bathroom home? I\'ll build the rest of your price '
                'list from that one number, and you can tweak any of it later.'),
    'booking_page': ('Good news: you already have a booking page where customers '
                     'pick a service, see your price and book themselves. The '
                     'next step is putting the link somewhere they\'ll see it, '
                     'like your Facebook or Instagram bio.'),
    'team': ('Who\'s cleaning for you? Give me a name and cell number for your '
             'first cleaner. If you\'re still cleaning yourself, add yourself.'),
    'client': ('Now add one real customer you already clean for: their name, '
               'phone, and address.'),
    'job': ('Last step: book a job for that customer and assign your cleaner. '
            'That\'s the moment Akye starts working for you. The cleaner gets a '
            'text with the address, the pay and the checklist.'),
}

STEP_LINKS = {
    'booking_page': ('Open my booking page', '/settings/booking-page'),
    'job': ('Book a job', '/bookings/new'),
}

DONE_PROMPT = ('That\'s every setup step done. One more thing worth doing: '
               'connect payments so customers can pay by card. You\'ll do that '
               'yourself on the Connections page, so your bank details stay '
               'with you.')
DONE_LINK = ('Connect payments', '/settings/connections')


def _next_step():
    import onboarding
    return onboarding.progress().get('next')


def nudge():
    """What to say next, and a button if the step lives on another page."""
    step = _next_step()
    if step is None:
        return DONE_PROMPT, _link_card(*DONE_LINK)
    text = STEP_PROMPTS.get(step['key'], step.get('why') or '')
    link = STEP_LINKS.get(step['key'])
    return text, (_link_card(*link) if link else None)


def greeting():
    text, link = nudge()
    opener = (f'Hi, I\'m {NAME}. I\'ll get you set up in a few minutes, one '
              f'question at a time. You can type your answers, ask me anything '
              f'about how Akye works, or skip a step.')
    if _next_step() is None:
        opener = f'Hi, I\'m {NAME}. You\'re all set up.'
    return f'{opener}\n\n{text}', link


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


def tool_offer_business(**kw):
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
    if problems:
        return ('Not offered. Ask them to check: ' + '; '.join(problems) + '.'), None
    if not payload:
        return 'Not offered: there was nothing to save.', None
    card = _offer('setup_save_business', payload, 'Save your business details',
                  lines, 'Save details')
    return ('A card is on screen with these details and a Save button. '
            'Nothing is saved until they press it.'), card


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
        'business (contact details customers see), pricing (one price for a '
        '2 bed / 2 bath standard clean sets the whole list), booking_page '
        '(share the self-booking link), team (add a cleaner, or themselves), '
        'client (add one real customer), job (book and assign a job). After '
        'that, payments are connected on the Connections page by the owner.\n'
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
ACTIONS = {
    'setup_save_business': save_business,
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
