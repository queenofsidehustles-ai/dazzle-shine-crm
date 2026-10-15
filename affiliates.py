"""Affiliate partners: who they are, what they brought, what they have earned.

A partner is someone who recommends Akye to cleaning-company owners (a coach,
a community owner, a bookkeeper) and earns a share of what those owners pay.
They get a link, `/p/<code>`, and a private page, `/partners`, where they can
see their own clicks, the companies that came through them, and what they have
earned and been paid.

## Money follows money

Commission accrues from a **paid Stripe invoice**, never from a signup or a
trial, and it is worked out from what was actually paid, before tax. Each paid
invoice is one row in the ledger and the invoice id is unique, so Stripe
delivering the same webhook five times earns one commission, not five. This is
the same rule `billing.py` is built on: state a fact, never increment a total.

A commission is held for `hold_days` (30 by default) before it is payable, to
cover refunds and chargebacks. Nothing has to run for the hold to end: a
commission is *payable* when it is accrued and its date has passed.

## It can never touch a customer

Nothing here changes a company's plan, status or access. A partner who is
paused, a payout that fails, a commission reversed -- all of it is between Akye
and the partner. The company that was referred never notices.

## What a partner can see about the companies they brought

The company name, when it signed up, and where it is in the journey (signed up,
set up, trial, paying, lapsed). Never an email address, a phone number, or
anything from inside the company's own CRM.

## Signing in

No passwords. The partner asks for a link by email; it is single-use, good for
an hour, and stored only as a hash. The link opens a page with a "Yes, sign me
in" button rather than signing in by being clicked, because mail scanners open
every link in a message (the same reason email_confirm.py works this way).
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select, update

import control_plane
from control_plane import (affiliate_clicks, affiliate_commissions,
                           affiliate_logins, affiliate_payouts, affiliates,
                           organizations)

STATUSES = ('pending', 'active', 'paused', 'ended')

# 30% of what the customer paid, for the first 12 months, payable after 30 days.
DEFAULT_RATE_BPS = 3000
DEFAULT_MONTHS = 12
DEFAULT_HOLD_DAYS = 30

LOGIN_MINUTES = 60
# Links an address may request in an hour before further requests are quietly
# ignored. Enough for a lost email; not enough to use us as a mailer.
LOGIN_REQUESTS_PER_HOUR = 3

_DAYS_PER_MONTH = 30.4375

CODE_RE = re.compile(r'^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Never a code: they read as something official, or they are paths of ours.
RESERVED_CODES = frozenset({
    'admin', 'akye', 'api', 'console', 'partners', 'partner', 'support',
    'billing', 'login', 'signup', 'static', 'www', 'help', 'team', 'staff',
})


def normalize_code(value):
    return re.sub(r'[^a-z0-9-]', '', (value or '').strip().lower()).strip('-')[:40]


def valid_code(code):
    return bool(code) and bool(CODE_RE.match(code)) and code not in RESERVED_CODES


def suggest_code(name):
    s = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')
    s = re.sub(r'-+', '-', s)[:30].strip('-')
    return s if valid_code(s) else ''


# Mailbox providers anybody can open an address at. Sharing one of these says
# nothing about two people being the same; sharing a business domain might.
FREE_MAIL = frozenset({
    'gmail.com', 'googlemail.com', 'yahoo.com', 'ymail.com', 'outlook.com',
    'hotmail.com', 'live.com', 'msn.com', 'icloud.com', 'me.com', 'mac.com',
    'aol.com', 'proton.me', 'protonmail.com', 'comcast.net', 'att.net',
    'sbcglobal.net', 'verizon.net', 'gmx.com', 'mail.com', 'zoho.com',
})


def normalize_email(email):
    """The mailbox an address really delivers to.

    `dana+akye@gmail.com` and `d.ana@gmail.com` are `dana@gmail.com`: a
    partner who signs up with a variant of their own address is still the
    partner. Dots are ignored only where the provider ignores them (Gmail)."""
    email = _clean_email(email)
    if '@' not in email:
        return email
    local, domain = email.rsplit('@', 1)
    local = local.split('+', 1)[0]
    if domain in ('gmail.com', 'googlemail.com'):
        local, domain = local.replace('.', ''), 'gmail.com'
    return f'{local}@{domain}'


def self_referral(partner_email, owner_email):
    """Is this signup the partner introducing themselves?

    'same'   the same mailbox: drop the credit, it is not an introduction.
    'review' the same business domain (and not a free mail provider): credit
             it, but hold the payout for a person -- it could be a colleague
             or the partner's own company, and only a person can tell.
    None     nothing suggests it.

    Only email is checked here. Where the Stripe card fingerprint is known, a
    card shared with the partner is the stronger signal; see the console."""
    a, b = normalize_email(partner_email), normalize_email(owner_email)
    if not a or not b:
        return None
    if a == b:
        return 'same'
    da, db = a.rsplit('@', 1)[-1], b.rsplit('@', 1)[-1]
    if da == db and da not in FREE_MAIL:
        return 'review'
    return None


def _clean_email(email):
    return (email or '').strip().lower()


# ---------------------------------------------------------------------------
# The partners themselves
# ---------------------------------------------------------------------------

def _row(conn, *where):
    row = conn.execute(select(affiliates).where(*where)).mappings().first()
    return dict(row) if row else None


def find(engine, affiliate_id):
    with engine.connect() as conn:
        return _row(conn, affiliates.c.id == affiliate_id)


def find_by_code(engine, code):
    code = normalize_code(code)
    if not code:
        return None
    with engine.connect() as conn:
        return _row(conn, affiliates.c.code == code)


def find_by_email(engine, email):
    email = _clean_email(email)
    if not email:
        return None
    with engine.connect() as conn:
        return _row(conn, affiliates.c.email == email)


def all_affiliates(engine):
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            select(affiliates).order_by(affiliates.c.created_at.desc(),
                                        affiliates.c.id.desc())).mappings()]


def create(engine, name, email, code=None, status='active',
           rate_bps=DEFAULT_RATE_BPS, months=DEFAULT_MONTHS,
           hold_days=DEFAULT_HOLD_DAYS, created_by=None, notes=None):
    """Add a partner. Raises ValueError with a sentence a person can act on."""
    name = (name or '').strip()[:200]
    email = _clean_email(email)
    code = normalize_code(code) or suggest_code(name)
    if not name:
        raise ValueError('A partner needs a name.')
    if not EMAIL_RE.match(email):
        raise ValueError(f'{email or "That"} is not an email address.')
    if not valid_code(code):
        raise ValueError(
            'A code is 3 to 40 letters, numbers or hyphens, and cannot be a '
            'word we use ourselves.')
    if status not in STATUSES:
        raise ValueError(f'{status!r} is not a status.')
    if not 0 <= int(rate_bps) <= 10000:
        raise ValueError('The rate must be between 0% and 100%.')
    if not 1 <= int(months) <= 60:
        raise ValueError('Months of commission must be between 1 and 60.')
    if not 0 <= int(hold_days) <= 180:
        raise ValueError('The hold must be between 0 and 180 days.')
    if find_by_code(engine, code):
        raise ValueError(f'The code {code!r} is already taken.')
    # A partner code is a different namespace from a company address (/p/ and
    # /r/ are different paths and different cookie fields), but a code that is
    # also a company's address invites a support conversation nobody wants.
    if control_plane.find(engine, code):
        raise ValueError(f'{code!r} is already a company address. Pick another code.')
    if find_by_email(engine, email):
        raise ValueError(f'{email} is already a partner.')
    with engine.begin() as conn:
        conn.execute(insert(affiliates).values(
            code=code, name=name, email=email, status=status,
            commission_bps=int(rate_bps), commission_months=int(months),
            hold_days=int(hold_days), notes=(notes or '')[:500] or None,
            created_by=(created_by or '')[:200] or None,
            created_at=datetime.utcnow()))
    return find_by_code(engine, code)


def set_status(engine, affiliate_id, status):
    if status not in STATUSES:
        raise ValueError(f'{status!r} is not a status.')
    with engine.begin() as conn:
        conn.execute(update(affiliates).where(affiliates.c.id == affiliate_id)
                     .values(status=status))


def accept_terms(engine, affiliate_id, when=None):
    with engine.begin() as conn:
        conn.execute(update(affiliates).where(
            affiliates.c.id == affiliate_id,
            affiliates.c.terms_accepted_at.is_(None))
            .values(terms_accepted_at=when or datetime.utcnow()))


def active_partner(engine, code):
    """The partner for a link, if the link should be honoured."""
    partner = find_by_code(engine, code)
    return partner if partner and partner['status'] == 'active' else None


# ---------------------------------------------------------------------------
# Clicks
# ---------------------------------------------------------------------------

def record_click(engine, affiliate_id, campaign=None, landing=None, when=None):
    with engine.begin() as conn:
        conn.execute(insert(affiliate_clicks).values(
            affiliate_id=affiliate_id, clicked_at=when or datetime.utcnow(),
            campaign=(campaign or '')[:120] or None,
            landing=(landing or '')[:120] or None))


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def _hash(raw):
    return hashlib.sha256((raw or '').encode()).hexdigest()


def login_requests_recent(engine, affiliate_id, now=None):
    since = (now or datetime.utcnow()) - timedelta(hours=1)
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(affiliate_logins).where(
                affiliate_logins.c.affiliate_id == affiliate_id,
                affiliate_logins.c.created_at >= since)).scalar() or 0


def issue_login(engine, affiliate_id, now=None):
    """A single-use sign-in token, or None when too many were asked for.

    Returns the raw token; only its hash is kept."""
    now = now or datetime.utcnow()
    if login_requests_recent(engine, affiliate_id, now) >= LOGIN_REQUESTS_PER_HOUR:
        return None
    raw = secrets.token_urlsafe(32)
    with engine.begin() as conn:
        conn.execute(insert(affiliate_logins).values(
            affiliate_id=affiliate_id, token_hash=_hash(raw), created_at=now,
            expires_at=now + timedelta(minutes=LOGIN_MINUTES)))
    return raw


def peek_login(engine, raw, now=None):
    """Is this token still good? Does not spend it (see the module docstring)."""
    now = now or datetime.utcnow()
    with engine.connect() as conn:
        row = conn.execute(select(affiliate_logins).where(
            affiliate_logins.c.token_hash == _hash(raw))).mappings().first()
    return bool(row and not row['used_at'] and row['expires_at'] > now)


def consume_login(engine, raw, now=None):
    """Spend a token. Returns the partner, or None for any kind of failure.

    One answer for unknown, expired, used and paused alike, so the response
    teaches nobody which tokens exist. Spending is a single UPDATE ... WHERE
    used_at IS NULL, so two requests racing with the same token cannot both
    win."""
    now = now or datetime.utcnow()
    with engine.begin() as conn:
        got = conn.execute(
            update(affiliate_logins)
            .where(affiliate_logins.c.token_hash == _hash(raw),
                   affiliate_logins.c.used_at.is_(None),
                   affiliate_logins.c.expires_at > now)
            .values(used_at=now)
            .returning(affiliate_logins.c.affiliate_id)).first()
        if not got:
            return None
        partner = _row(conn, affiliates.c.id == got[0])
        if not partner or partner['status'] not in ('active', 'pending', 'paused'):
            return None
        conn.execute(update(affiliates).where(affiliates.c.id == partner['id'])
                     .values(last_login_at=now))
    return partner


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

def _invoice_base_cents(invoice):
    """What commission is worked out on: what was paid, before tax.

    Tax is collected for a government, not earned, so a partner is not paid a
    share of it. Falls back to the amount paid when Stripe did not say."""
    paid = int(invoice.get('amount_paid') or 0)
    if paid <= 0:
        return 0
    excl = invoice.get('total_excluding_tax')
    if excl is not None:
        return max(0, min(paid, int(excl)))
    return max(0, paid - int(invoice.get('tax') or 0))


def accrue(engine, slug, invoice, now=None):
    """Record the commission a paid invoice earned. Returns the row, or None.

    Safe to call any number of times for the same invoice. Does nothing for a
    company with no partner, a free or fully discounted invoice, or an invoice
    past the partner's commission window. Never raises: a ledger problem must
    not be the reason a payment is treated as unprocessed."""
    try:
        return _accrue(engine, slug, invoice, now)
    except Exception as e:
        print(f'  ⚠️  affiliate commission not recorded: {type(e).__name__}: {e}')
        return None


def _accrue(engine, slug, invoice, now):
    now = now or datetime.utcnow()
    invoice_id = (invoice.get('id') or '').strip()
    if not invoice_id:
        return None
    org = control_plane.find(engine, slug)
    code = org and org.get('affiliate_code')
    if not code:
        return None
    partner = find_by_code(engine, code)
    if not partner:
        return None
    base = _invoice_base_cents(invoice)
    if base <= 0:
        return None
    paid_at = now
    transitions = invoice.get('status_transitions') or {}
    if transitions.get('paid_at'):
        paid_at = datetime.utcfromtimestamp(transitions['paid_at'])

    with engine.begin() as conn:
        again = conn.execute(select(affiliate_commissions).where(
            affiliate_commissions.c.stripe_invoice_id == invoice_id)).mappings().first()
        if again:
            return dict(again)
        first = conn.execute(
            select(func.min(affiliate_commissions.c.invoice_paid_at)).where(
                affiliate_commissions.c.affiliate_id == partner['id'],
                affiliate_commissions.c.org_slug == slug)).scalar()
        if first:
            ends = first + timedelta(
                days=partner['commission_months'] * _DAYS_PER_MONTH)
            if paid_at > ends:
                return None                       # past the 12 months
        commission = base * partner['commission_bps'] // 10000
        if commission <= 0:
            return None
        conn.execute(insert(affiliate_commissions).values(
            affiliate_id=partner['id'], org_slug=slug,
            stripe_invoice_id=invoice_id, invoice_paid_at=paid_at,
            amount_cents=base, rate_bps=partner['commission_bps'],
            commission_cents=commission, status='accrued',
            payable_at=paid_at + timedelta(days=partner['hold_days']),
            created_at=now))
        row = conn.execute(select(affiliate_commissions).where(
            affiliate_commissions.c.stripe_invoice_id == invoice_id)).mappings().first()
    return dict(row)


def reverse(engine, invoice_id, reason='refunded', now=None):
    """Cancel the commission an invoice earned (refund, chargeback).

    Only an unpaid commission is reversed here. One already paid out is left
    alone and reported to the caller as such, so staff can settle it by hand:
    quietly rewriting history that a partner has already been paid against is
    how a ledger stops being believed. Returns 'reversed', 'already paid',
    'already reversed' or 'none'."""
    now = now or datetime.utcnow()
    with engine.begin() as conn:
        row = conn.execute(select(affiliate_commissions).where(
            affiliate_commissions.c.stripe_invoice_id == invoice_id)).mappings().first()
        if not row:
            return 'none'
        if row['status'] == 'reversed':
            return 'already reversed'
        if row['status'] == 'paid':
            return 'already paid'
        conn.execute(update(affiliate_commissions).where(
            affiliate_commissions.c.id == row['id']).values(
                status='reversed', reversed_at=now,
                reversal_reason=(reason or '')[:200] or None))
    return 'reversed'


def _not_in_review():
    """Commissions whose company nobody has flagged for a second look."""
    flagged = select(organizations.c.slug).where(
        organizations.c.affiliate_flag.isnot(None))
    return affiliate_commissions.c.org_slug.notin_(flagged)


def payable_cents(engine, affiliate_id, now=None):
    now = now or datetime.utcnow()
    with engine.connect() as conn:
        return conn.execute(
            select(func.coalesce(func.sum(affiliate_commissions.c.commission_cents), 0))
            .where(affiliate_commissions.c.affiliate_id == affiliate_id,
                   affiliate_commissions.c.status == 'accrued',
                   affiliate_commissions.c.payable_at <= now,
                   _not_in_review())).scalar() or 0


def record_payout(engine, affiliate_id, created_by, method='transfer',
                  reference=None, note=None, now=None):
    """Pay out everything that is payable, as one payout. Returns it, or None.

    Records that money was sent; it does not send any. Marking the rows and
    writing the payout happen in one transaction, and rows are claimed by an
    UPDATE ... WHERE status = 'accrued', so two staff pressing the button at
    the same moment cannot pay the same commission twice."""
    now = now or datetime.utcnow()
    with engine.begin() as conn:
        rows = conn.execute(
            select(affiliate_commissions.c.id, affiliate_commissions.c.commission_cents)
            .where(affiliate_commissions.c.affiliate_id == affiliate_id,
                   affiliate_commissions.c.status == 'accrued',
                   affiliate_commissions.c.payable_at <= now,
                   _not_in_review())
            .with_for_update()).all()
        total = sum(r[1] for r in rows)
        if not rows or total <= 0:
            return None
        payout_id = conn.execute(insert(affiliate_payouts).values(
            affiliate_id=affiliate_id, amount_cents=total,
            method=(method or '')[:40] or None,
            reference=(reference or '')[:120] or None,
            note=(note or '')[:300] or None, paid_at=now,
            created_by=(created_by or '')[:200] or None
        ).returning(affiliate_payouts.c.id)).scalar()
        conn.execute(update(affiliate_commissions).where(
            affiliate_commissions.c.id.in_([r[0] for r in rows]),
            affiliate_commissions.c.status == 'accrued')
            .values(status='paid', payout_id=payout_id))
        row = conn.execute(select(affiliate_payouts).where(
            affiliate_payouts.c.id == payout_id)).mappings().first()
    return dict(row)


# ---------------------------------------------------------------------------
# What the partner sees
# ---------------------------------------------------------------------------

def journey(org, now=None):
    """Where one referred company is, in a word a partner can use.

    Deliberately coarse. A partner is told whether the owner is getting
    started, trialling, paying or gone -- not why, and nothing about the
    business itself."""
    now = now or datetime.utcnow()
    if org.get('status') in ('closing', 'closed'):
        return 'closed'
    sub = (org.get('subscription_status') or '').lower()
    if org.get('stripe_subscription_id') and sub == 'active':
        return 'paying'
    if org.get('stripe_subscription_id') and sub == 'past_due':
        return 'payment late'
    if sub in ('canceled', 'cancelled', 'unpaid', 'incomplete_expired'):
        return 'cancelled'
    ends = org.get('trial_ends_at')
    if org.get('activated_at'):
        if ends and ends <= now and not org.get('stripe_subscription_id'):
            return 'trial ended'
        return 'in trial'
    return 'signed up'


def _by_day(rows, key, days, now):
    out = {}
    for r in rows:
        d = r[key].date()
        out[d] = out.get(d, 0) + 1
    today = now.date()
    return [(today - timedelta(days=i), out.get(today - timedelta(days=i), 0))
            for i in range(days - 1, -1, -1)]


def portal(engine, partner, now=None):
    """Everything the partner page shows, in one dict."""
    now = now or datetime.utcnow()
    pid, code = partner['id'], partner['code']
    since30 = now - timedelta(days=30)

    with engine.connect() as conn:
        clicks = [dict(r) for r in conn.execute(
            select(affiliate_clicks).where(affiliate_clicks.c.affiliate_id == pid)
            .order_by(affiliate_clicks.c.clicked_at.desc())).mappings()]
        orgs = [dict(r) for r in conn.execute(
            select(organizations).where(organizations.c.affiliate_code == code)
            .order_by(organizations.c.created_at.desc())).mappings()]
        ledger = [dict(r) for r in conn.execute(
            select(affiliate_commissions)
            .where(affiliate_commissions.c.affiliate_id == pid)
            .order_by(affiliate_commissions.c.invoice_paid_at.desc(),
                      affiliate_commissions.c.id.desc())).mappings()]
        payouts = [dict(r) for r in conn.execute(
            select(affiliate_payouts)
            .where(affiliate_payouts.c.affiliate_id == pid)
            .order_by(affiliate_payouts.c.paid_at.desc(),
                      affiliate_payouts.c.id.desc())).mappings()]

    companies = []
    names = {}
    in_review = {o['slug'] for o in orgs if o.get('affiliate_flag')}
    for o in orgs:
        if o.get('is_test') or o.get('is_demo'):
            continue
        stage = journey(o, now)
        names[o['slug']] = o.get('name') or o['slug']
        earned = sum(c['commission_cents'] for c in ledger
                     if c['org_slug'] == o['slug'] and c['status'] != 'reversed')
        companies.append({'name': names[o['slug']], 'signed_up': o.get('created_at'),
                          'stage': stage, 'earned_cents': earned,
                          'campaign': o.get('signup_campaign') or '',
                          'slug': o['slug'], 'flag': o.get('affiliate_flag'),
                          'activated': bool(o.get('activated_at')),
                          'paying': stage == 'paying'})

    accrued = [c for c in ledger if c['status'] == 'accrued']
    held = lambda c: c['payable_at'] > now or c['org_slug'] in in_review
    payable = sum(c['commission_cents'] for c in accrued if not held(c))
    pending = sum(c['commission_cents'] for c in accrued if held(c))
    paid = sum(c['commission_cents'] for c in ledger if c['status'] == 'paid')
    reversed_ = sum(c['commission_cents'] for c in ledger if c['status'] == 'reversed')
    next_payable = min((c['payable_at'] for c in accrued
                        if c['payable_at'] > now and c['org_slug'] not in in_review),
                       default=None)

    for c in ledger:
        c['company'] = names.get(c['org_slug']) or c['org_slug']
        if c['status'] == 'accrued':
            c['state'] = ('in review' if c['org_slug'] in in_review
                          else 'payable' if c['payable_at'] <= now else 'on hold')
        else:
            c['state'] = c['status']

    # By campaign tag: the one question a partner can act on, "which of my
    # posts and emails actually brought people?".
    campaigns = {}
    for c in clicks:
        row = campaigns.setdefault(c['campaign'] or '(no tag)',
                                   {'clicks': 0, 'signed_up': 0, 'activated': 0, 'paying': 0})
        row['clicks'] += 1
    for co in companies:
        row = campaigns.setdefault(co['campaign'] or '(no tag)',
                                   {'clicks': 0, 'signed_up': 0, 'activated': 0, 'paying': 0})
        row['signed_up'] += 1
        row['activated'] += 1 if co['activated'] else 0
        row['paying'] += 1 if co['paying'] else 0

    def pct(part, whole):
        return round(100 * part / whole) if whole else None

    n_signed = len(companies)
    n_active = sum(1 for c in companies if c['activated'])
    n_paying = sum(1 for c in companies if c['paying'])
    recent_clicks = [c for c in clicks if c['clicked_at'] >= since30]
    return {
        'partner': partner,
        'clicks_total': len(clicks),
        'clicks_30': len(recent_clicks),
        'daily_clicks': _by_day(recent_clicks, 'clicked_at', 30, now),
        'signed_up': n_signed,
        'activated': n_active,
        'paying': n_paying,
        'click_to_signup_pct': pct(n_signed, len(clicks)),
        'signup_to_paying_pct': pct(n_paying, n_signed),
        'companies': companies,
        'campaigns': sorted(campaigns.items(), key=lambda kv: (-kv[1]['clicks'], kv[0])),
        'ledger': ledger,
        'payouts': payouts,
        'payable_cents': payable,
        'pending_cents': pending,
        'paid_cents': paid,
        'reversed_cents': reversed_,
        'lifetime_cents': payable + pending + paid,
        'next_payable_at': next_payable,
        'rate_pct': partner['commission_bps'] / 100,
    }


def money(cents):
    """12345 -> '$123.45'. For templates."""
    cents = int(cents or 0)
    sign = '-' if cents < 0 else ''
    return f'{sign}${abs(cents) // 100:,}.{abs(cents) % 100:02d}'
