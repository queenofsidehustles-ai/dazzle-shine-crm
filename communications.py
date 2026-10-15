"""Every automated email the product sends, in one list.

The console's Communications page is built from this, and so is every on/off
switch. Adding an email to trial_nudges.py or lead_nurture.py means adding
one line here, so it appears in the console the day it ships -- there is no
second place to forget.

Two audiences:

    owner  a cleaning company's owner, about their own account (trial_nudges)
    lead   somebody who came close and did not sign up (lead_nurture)

The emails a cleaning company sends its own customers are not here. They
belong to that company and are edited in its own Email Templates page.
"""
from datetime import datetime, timedelta

# (key, audience, label, when, who)
CATALOG = [
    ('welcome', 'owner', 'Welcome + your address + confirm code',
     'At signup', 'Everyone'),
    ('day1', 'owner', 'Get the schedule out of your head',
     'Day 1', 'Not set up yet'),
    ('day2', 'owner', 'The jobs you lose while you are cleaning',
     'Day 2', 'Everyone on a trial'),
    ('day4', 'owner', 'What usually gets in the way',
     'Day 4', 'Not set up yet'),
    ('day5', 'owner', 'Your customer list is one lost phone from gone',
     'Day 5', 'Not set up yet'),
    ('start_7', 'owner', 'Your 30 days have not started',
     'Day 7', 'Not set up yet'),
    ('start_21', 'owner', 'Days left to start your trial',
     'Day 21', 'Not set up yet'),
    ('activated', 'owner', 'Your 30 days just started',
     'The moment they add a cleaner and a customer', 'Just set up'),
    ('first_booking', 'owner', 'Somebody booked you through your own page',
     'The first online booking', 'On a trial'),
    ('feature', 'owner', 'Before your trial ends, try this',
     'Trial day 8 to 10', 'A setup step still undone'),
    ('ending', 'owner', 'Days left of everything',
     '3 days before the trial ends', 'On a trial'),
    ('ended', 'owner', 'Your trial has finished',
     'The day it ends', 'Trial just ended'),
    ('winback', 'owner', 'Still doing it the hard way?',
     'A week after it ends', 'Used it, did not upgrade'),
    ('nurture_1', 'lead', 'What it actually costs to start a cleaning business',
     'Day 1', 'Started signing up, or asked for early access'),
    ('nurture_2', 'lead', 'How to price a cleaning job',
     'Day 4', 'Same, until they sign up'),
    ('nurture_3', 'lead', 'The decision that gets new cleaning owners fined',
     'Day 8', 'Same, until they sign up'),
    ('nurture_4', 'lead', 'Last one from us',
     'Day 13', 'Same, then nothing'),
]

# Whole-sequence switches, checked before the per-email ones.
ALL_OWNER = 'owner_all'
ALL_LEAD = 'lead_all'

# The welcome email carries their web address and confirm code. Switching it
# off would leave a new owner with no written record of either, so it is
# always on and the console says so.
ALWAYS_ON = {'welcome'}

LABELS = {k: label for k, _a, label, _w, _who in CATALOG}


def audience(key):
    for k, a, *_ in CATALOG:
        if k == key:
            return a
    return None


def is_on(key, switch_map=None):
    """Whether this email may be sent. Never raises; anything unreadable
    means on, which is how it behaved before switches existed."""
    if key in ALWAYS_ON:
        return True
    try:
        if switch_map is None:
            import control_plane
            import provisioning
            switch_map = control_plane.switches(provisioning._engine())
        master = ALL_LEAD if audience(key) == 'lead' else ALL_OWNER
        return switch_map.get(master, True) and switch_map.get(key, True)
    except Exception:
        return True


def sent_counts(engine, days=30):
    """{key: how many sent in the last `days`} for the catalog table."""
    import control_plane
    since = datetime.utcnow() - timedelta(days=days)
    out = {}
    for m in control_plane.product_messages_for(engine, since=since, limit=5000):
        if m.get('ok'):
            out[m['kind']] = out.get(m['kind'], 0) + 1
    for m in control_plane.lead_messages(engine, limit=5000):
        by = (m.get('sent_by') or '')
        if m.get('ok') and by.startswith('nurture ') and m.get('sent_at') \
                and m['sent_at'] >= since:
            key = 'nurture_' + by.split(' ', 1)[1]
            out[key] = out.get(key, 0) + 1
    return out


def recent(engine, limit=100):
    """Owner and lead emails together, newest first, in one shape."""
    import control_plane
    rows = []
    for m in control_plane.product_messages_for(engine, limit=limit):
        rows.append({'when': m['sent_at'], 'to': m['to_address'],
                     'who': m.get('org_slug'), 'kind': m.get('kind'),
                     'label': LABELS.get(m.get('kind'), m.get('kind')),
                     'subject': m.get('subject'), 'ok': m.get('ok'),
                     'detail': m.get('detail'), 'by': m.get('sent_by'),
                     'audience': 'owner'})
    for m in control_plane.lead_messages(engine, limit=limit):
        by = m.get('sent_by') or ''
        key = ('nurture_' + by.split(' ', 1)[1]) if by.startswith('nurture ') else None
        rows.append({'when': m['sent_at'], 'to': m['to_address'],
                     'who': m.get('company') or m.get('name'),
                     'kind': key or m.get('channel'),
                     'label': LABELS.get(key) if key else
                     ('Text from the console' if m.get('channel') == 'sms'
                      else 'Email from the console'),
                     'subject': m.get('subject'), 'ok': m.get('ok'),
                     'detail': m.get('detail'),
                     'by': 'auto' if key else by, 'audience': 'lead'})
    rows.sort(key=lambda r: r['when'] or datetime.min, reverse=True)
    return rows[:limit]


def history_for(engine, needle):
    """Everything sent to one person or company, found by email, company
    address (slug) or name. Returns (matches, rows)."""
    import control_plane
    needle = (needle or '').strip().lower()
    if not needle:
        return [], []
    orgs = [o for o in control_plane.all_orgs(engine)
            if needle in (o.get('slug') or '').lower()
            or needle in (o.get('name') or '').lower()
            or needle == (o.get('owner_email') or '').lower()]
    leads = [l for l in control_plane.all_leads(engine)
             if needle == (l.get('email') or '').lower()
             or needle in (l.get('company') or '').lower()
             or needle in (l.get('name') or '').lower()]
    rows = []
    for o in orgs[:10]:
        for m in control_plane.product_messages_for(engine, slug=o['slug']):
            rows.append({'when': m['sent_at'], 'to': m['to_address'],
                         'who': o.get('name'),
                         'label': LABELS.get(m['kind'], m['kind']),
                         'subject': m.get('subject'), 'ok': m.get('ok'),
                         'detail': m.get('detail'), 'by': m.get('sent_by')})
    seen = set()
    for l in leads[:10]:
        email = (l.get('email') or '').lower()
        if not email or email in seen:
            continue
        seen.add(email)
        for m in control_plane.lead_messages_for(engine, email):
            by = m.get('sent_by') or ''
            key = ('nurture_' + by.split(' ', 1)[1]) if by.startswith('nurture ') else None
            rows.append({'when': m['sent_at'], 'to': m['to_address'],
                         'who': l.get('company') or l.get('name'),
                         'label': LABELS.get(key) if key else
                         ('Text from the console' if m.get('channel') == 'sms'
                          else 'Email from the console'),
                         'subject': m.get('subject'), 'ok': m.get('ok'),
                         'detail': m.get('detail'),
                         'by': 'auto' if key else by})
    rows.sort(key=lambda r: r['when'] or datetime.min, reverse=True)
    return {'orgs': orgs[:10], 'leads': leads[:10]}, rows


def sample_preview(key):
    """(subject, html) for a sample company, so the console can show what an
    email looks like without anybody's real details in it."""
    import billing
    import lead_nurture
    import lead_outreach
    import trial_nudges
    now = datetime.utcnow()
    began = now - timedelta(days=9)
    org = {'slug': 'sparkle', 'name': 'Sparkle Cleaning',
           'owner_email': 'owner@example.com', 'status': 'active',
           'created_at': now - timedelta(days=11), 'plan': 'scale',
           'subscription_status': 'trialing', 'activated_at': began,
           'trial_ends_at': began + timedelta(days=billing.TRIAL_DAYS),
           'nudges_sent': None}
    if key == 'welcome':
        import email_confirm
        import welcome_email
        host = 'sparkle.' + (__import__('product').domain() or 'akyehq.com')
        return ('Sparkle Cleaning is set up — here is your address',
                welcome_email.build('Sparkle Cleaning', 'owner@example.com', host,
                                    'Dana', '123456', f'https://{host}/confirm-email/…'))
    if key and key.startswith('nurture_'):
        step = int(key.split('_')[1])
        lead = {'email': 'lee@example.com', 'name': 'Lee Carter',
                'company': 'Halfway Cleaning', 'source': 'abandoned_signup'}
        subject, body = lead_nurture.compose(lead, step)
        return subject, lead_outreach.email_html(body, lead['email'])
    if key in ('ended', 'winback'):
        org['trial_ends_at'] = now - timedelta(days=1)
    step = {'title': 'Share your booking page',
            'why': 'A page where customers pick a service, see your price and book.',
            'cta': 'Show me my page', 'link': '/settings/booking-page'}
    return trial_nudges.compose(org, key, step)
