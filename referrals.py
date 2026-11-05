"""Company-to-company referrals: tell another cleaning owner, you both get a
free month.

Every company already has a link (`/r/<its address>`, shown on Billing) and a
signup through it is recorded as `referred_by` (control_plane._signup_attribution).
This module is what that link now earns.

## Money follows money

A reward is earned by the referred company's first PAID invoice, never by a
signup or a trial: nothing is given away for a company that never pays. The
reward is one row per side in `referral_rewards`, unique on (referred company,
side), so Stripe delivering the same webhook five times earns one reward, and a
second invoice earns none (the same rule affiliates.py and billing.py are built
on: state a fact, never increment a total).

## What each side gets

A month's price, as a credit on the customer's Stripe balance, which comes off
their next invoice by itself. Nothing is mailed, nothing has to be redeemed.

  referred   the amount of their own first paid invoice
  referrer   their own monthly price (the amount of the referred invoice when
             that is not known), at most MAX_CREDIT_CENTS either way

A referrer with nothing to credit yet (still on a trial, no Stripe customer) is
`pending`: the credit is applied on their own first payment.

## Limits

* MONTHS_CAP (12) rewards per referrer. The thirteenth referred company still
  gets its own month; the referrer's row says `capped`.
* A company referred by an affiliate partner earns no company reward: the
  partner already earns on it (attribution.py ranks a partner above a referral).
* Not for test or demo companies on either side.
* Not when the two companies are the same person: the same mailbox (affiliates.
  normalize_email) or the same phone number. Recorded as `blocked`, with why.
  (The card is not compared. A shared card is the stronger signal, and the
  console can see it in Stripe.)
* A fully refunded first invoice reverses both rewards. One not yet credited is
  cancelled; one already credited is taken back with a matching charge to the
  customer's balance.
* `referral_rewards` in the console switches (platform_switches) turns it all
  off, and it fails CLOSED: an unreadable switch is not permission to credit.

## It never touches access

Nothing here changes a plan, a status or what a company can do. A failed Stripe
call leaves the reward `pending` with the error written down; it is retried on
that company's next paid invoice.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select, update

import control_plane
from control_plane import organizations, referral_refunds, referral_rewards

MONTHS_CAP = 12
MAX_CREDIT_CENTS = 50000          # no single credit is ever more than $500
SWITCH = 'referral_rewards'

LIVE = ('pending', 'applying', 'applied')

# A claimed credit whose answer never came back is looked at again after this.
CLAIM_STALE = timedelta(minutes=10)


# ---------------------------------------------------------------------------
# Is it on, and who is who
# ---------------------------------------------------------------------------

def enabled(engine=None):
    import platform_switches
    return platform_switches.is_on(SWITCH, engine)


def link_for(org):
    """This company's referral link on the product site, or None on a
    single-business install where there is no product site to send anybody to."""
    import product
    if not org or not product.domain():
        return None
    host = product.canonical_host() or product.domain()
    return f'{product.scheme_for(host)}://{host}/r/{org["slug"]}'


def _same_person(a, b):
    """Why these two companies look like one person, or None."""
    import affiliates
    ea, eb = affiliates.normalize_email(a.get('owner_email')), \
        affiliates.normalize_email(b.get('owner_email'))
    if ea and eb and ea == eb:
        return 'same email address'
    pa, pb = (a.get('owner_phone') or '').strip(), (b.get('owner_phone') or '').strip()
    if pa and pb and pa == pb:
        return 'same phone number'
    return None


def _clamp(cents):
    return max(0, min(int(cents or 0), MAX_CREDIT_CENTS))


# ---------------------------------------------------------------------------
# Earning
# ---------------------------------------------------------------------------

def earn(engine, slug, invoice, now=None):
    """The rewards a paid invoice earned, as rows ([] when it earned none).

    Safe to call any number of times for the same company. Lets a database
    error raise on purpose: the Stripe webhook turns it into a 500, Stripe
    retries, and the retry is safe because (referred company, side) is unique.
    """
    now = now or datetime.utcnow()
    invoice_id = (invoice.get('id') or '').strip()
    if not invoice_id:
        return []
    org = control_plane.find(engine, slug)
    if not org or org.get('is_test') or org.get('is_demo'):
        return []
    referrer_slug = org.get('referred_by')
    if not referrer_slug or org.get('affiliate_code'):
        return []
    referrer = control_plane.find(engine, referrer_slug)
    if not referrer or referrer.get('is_test') or referrer.get('is_demo'):
        return []
    import affiliates
    base = affiliates._invoice_base_cents(invoice)
    if base <= 0:
        return []                    # a free or fully discounted invoice earns nothing
    if not enabled(engine):
        return []                    # switched off: nothing recorded, so it can still be earned

    with engine.begin() as conn:
        again = conn.execute(select(referral_rewards).where(
            referral_rewards.c.referred_slug == slug)).mappings().all()
        if again:
            return [dict(r) for r in again]          # the first paid invoice only

        # Serialise concurrent first invoices for the same referrer, so the cap
        # cannot be passed by two at once. (Ignored by databases without row locks.)
        conn.execute(select(organizations.c.slug).where(
            organizations.c.slug == referrer_slug).with_for_update())

        refunded = conn.execute(select(referral_refunds.c.stripe_invoice_id).where(
            referral_refunds.c.stripe_invoice_id == invoice_id)).first()
        why = _same_person(org, referrer)
        if refunded:
            # Refunded before this payment event reached us (they can arrive in
            # either order): earn nothing, and do not let a later invoice take
            # the place of the one that was refunded.
            plan = [('referred', 0, 'reversed', 'refunded before it was recorded'),
                    ('referrer', 0, 'reversed', 'refunded before it was recorded')]
        elif why:
            plan = [('referred', 0, 'blocked', why), ('referrer', 0, 'blocked', why)]
        else:
            used = conn.execute(select(func.count()).select_from(referral_rewards).where(
                referral_rewards.c.referrer_slug == referrer_slug,
                referral_rewards.c.side == 'referrer',
                referral_rewards.c.status.in_(LIVE))).scalar() or 0
            theirs = _clamp(base)
            mine = _clamp(referrer.get('mrr_cents')) or theirs
            if used >= MONTHS_CAP:
                plan = [('referred', theirs, 'pending', None),
                        ('referrer', 0, 'capped',
                         f'already earned {MONTHS_CAP} free months')]
            else:
                plan = [('referred', theirs, 'pending', None),
                        ('referrer', mine, 'pending', None)]
        for side, cents, status, reason in plan:
            conn.execute(insert(referral_rewards).values(
                referrer_slug=referrer_slug, referred_slug=slug, side=side,
                stripe_invoice_id=invoice_id, amount_cents=cents, status=status,
                reason=reason, created_at=now))
        rows = [dict(r) for r in conn.execute(select(referral_rewards).where(
            referral_rewards.c.referred_slug == slug)).mappings()]
    return rows


# ---------------------------------------------------------------------------
# Crediting
# ---------------------------------------------------------------------------

def _balance_transaction(customer_id, cents, description, key, metadata):
    """One entry on a Stripe customer's balance. Negative is a credit (it comes
    off their next invoice), positive is a charge. Replaced in tests."""
    import stripe
    import billing
    stripe.api_key = billing.stripe_key()
    return stripe.Customer.create_balance_transaction(
        customer_id, amount=cents, currency='usd', description=description,
        metadata=metadata, idempotency_key=key)


def _recent_balance_transactions(customer_id):
    """The customer's latest balance entries, as dicts. Replaced in tests."""
    import stripe
    import billing
    stripe.api_key = billing.stripe_key()
    page = stripe.Customer.list_balance_transactions(customer_id, limit=100)
    return [dict(t) for t in page.get('data', [])]


def _already_at_stripe(customer_id, reward_id, credit):
    """The balance entry this reward already made at Stripe, or None.

    Stripe forgets an idempotency key after a day, so an attempt whose answer
    never came back and is retried later could otherwise be made twice. The
    reward's id travels in the entry's metadata; look for it before resending."""
    for t in _recent_balance_transactions(customer_id):
        meta = t.get('metadata') or {}
        if meta.get('referral_reward_id') != str(reward_id):
            continue
        amount = t.get('amount') or 0
        if (amount < 0) == credit:
            return t
    return None


def _beneficiary(row):
    return row['referred_slug'] if row['side'] == 'referred' else row['referrer_slug']


def _txn_id(txn):
    return txn.get('id') if hasattr(txn, 'get') else getattr(txn, 'id', None)


def apply_pending(engine, slug, now=None):
    """Credit whatever is waiting for this company. Never raises.

    Each reward is claimed first (pending -> applying, in one statement), so
    two workers, or a credit and a refund, cannot both act on it. A Stripe
    failure puts it back to pending with the error written down; the next paid
    invoice from this company tries again. A reward that has been attempted
    before is looked up at Stripe before it is sent again."""
    now = now or datetime.utcnow()
    done = []
    try:
        org = control_plane.find(engine, slug)
        customer = org and org.get('stripe_customer_id')
        if not customer or org.get('is_test') or org.get('is_demo'):
            return done
        if not enabled(engine):
            return done
        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(
                select(referral_rewards).where(
                    referral_rewards.c.status.in_(('pending', 'applying')),
                    referral_rewards.c.amount_cents > 0))
                    .mappings() if _beneficiary(r) == slug]
    except Exception:
        return done
    for row in rows:
        try:
            with engine.begin() as conn:
                claimed = conn.execute(update(referral_rewards).where(
                    referral_rewards.c.id == row['id'],
                    (referral_rewards.c.status == 'pending') |
                    ((referral_rewards.c.status == 'applying') &
                     (referral_rewards.c.attempted_at < now - CLAIM_STALE)))
                    .values(status='applying', attempted_at=now)).rowcount
            if not claimed:
                continue                     # somebody else has it
            txn = _already_at_stripe(customer, row['id'], True) \
                if row['attempted_at'] else None
            if txn is None:
                who = row['referrer_slug'] if row['side'] == 'referred' else row['referred_slug']
                note = ('Referral: a month on us for joining through a friend'
                        if row['side'] == 'referred'
                        else 'Referral: a month on us, thanks for telling a friend')
                txn = _balance_transaction(
                    customer, -row['amount_cents'], note, f'referral-reward-{row["id"]}',
                    {'referral_reward_id': str(row['id']), 'side': row['side'],
                     'other_company': who})
            with engine.begin() as conn:
                conn.execute(update(referral_rewards).where(
                    referral_rewards.c.id == row['id'],
                    referral_rewards.c.status == 'applying').values(
                        status='applied', applied_at=now, last_error=None,
                        stripe_balance_txn=_txn_id(txn)))
            done.append(row['id'])
        except Exception as e:                          # noqa: BLE001
            try:
                with engine.begin() as conn:
                    conn.execute(update(referral_rewards).where(
                        referral_rewards.c.id == row['id'],
                        referral_rewards.c.status == 'applying').values(
                            status='pending',
                            last_error=f'{type(e).__name__}: {e}'[:300]))
            except Exception:
                pass
    return done


# ---------------------------------------------------------------------------
# Taking it back
# ---------------------------------------------------------------------------

class ReversalIncomplete(RuntimeError):
    """A refund could not be fully carried out yet. Raised to the Stripe
    webhook so it answers 500 and Stripe sends the refund again."""


def reverse(engine, invoice_id, reason='refunded', now=None):
    """Undo the rewards a fully refunded first invoice earned. Returns the ids.

    Not yet credited: cancelled in one statement, so a credit being made at
    that moment cannot be left recorded as reversed. Already credited: a
    matching charge to the customer's balance. The refund is also written
    down, so if the payment it undoes has not been recorded yet, it never earns.

    Raises ReversalIncomplete when a credit is mid-flight or a clawback failed:
    nothing is lost, the rows stay as they were, and the refund event is
    redelivered."""
    now = now or datetime.utcnow()
    out, problems = [], []
    with engine.begin() as conn:
        if not conn.execute(select(referral_refunds.c.stripe_invoice_id).where(
                referral_refunds.c.stripe_invoice_id == invoice_id)).first():
            conn.execute(insert(referral_refunds).values(
                stripe_invoice_id=invoice_id, created_at=now))
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(select(referral_rewards).where(
            referral_rewards.c.stripe_invoice_id == invoice_id,
            referral_rewards.c.status.in_(LIVE))).mappings()]
    for row in rows:
        if row['status'] == 'applying':
            problems.append(f'reward {row["id"]} is being credited right now')
            continue
        try:
            if row['status'] == 'applied' and row['amount_cents'] > 0:
                org = control_plane.find(engine, _beneficiary(row))
                customer = org and org.get('stripe_customer_id')
                if customer and not _already_at_stripe(customer, row['id'], False):
                    _balance_transaction(
                        customer, row['amount_cents'],
                        f'Referral credit taken back ({reason})',
                        f'referral-clawback-{row["id"]}',
                        {'referral_reward_id': str(row['id'])})
            with engine.begin() as conn:
                changed = conn.execute(update(referral_rewards).where(
                    referral_rewards.c.id == row['id'],
                    referral_rewards.c.status == row['status']).values(
                        status='reversed', reversed_at=now,
                        reason=(f'{reason}')[:200])).rowcount
            if changed:
                out.append(row['id'])
            else:
                problems.append(f'reward {row["id"]} changed while being reversed')
        except Exception as e:                          # noqa: BLE001
            problems.append(f'reward {row["id"]}: {type(e).__name__}: {e}')
            try:
                with engine.begin() as conn:
                    conn.execute(update(referral_rewards).where(
                        referral_rewards.c.id == row['id']).values(
                            last_error=f'reversal: {type(e).__name__}: {e}'[:300]))
            except Exception:
                pass
    if problems:
        raise ReversalIncomplete('; '.join(problems)[:400])
    return out


# ---------------------------------------------------------------------------
# What an owner sees
# ---------------------------------------------------------------------------

def summary(engine, slug):
    """What this company's referrals have done, for its Billing page and its
    dashboard. Company names and states only -- never an email or a number.

    {'signed_up': n, 'paying': n, 'months': n, 'cap': 12, 'waiting': n,
     'rows': [{'name', 'state', 'credit'}]}"""
    out = {'signed_up': 0, 'paying': 0, 'months': 0, 'cap': MONTHS_CAP,
           'waiting': 0, 'rows': []}
    try:
        referred = control_plane.referred_by(engine, slug)
        with engine.connect() as conn:
            rewards = {r['referred_slug']: dict(r) for r in conn.execute(
                select(referral_rewards).where(
                    referral_rewards.c.referrer_slug == slug,
                    referral_rewards.c.side == 'referrer')).mappings()}
    except Exception:
        return out
    out['signed_up'] = len(referred)
    for o in referred:
        r = rewards.get(o['slug'])
        if not r:
            state = 'Signed up'
        elif r['status'] == 'applied':
            state = 'Paying · free month credited'
        elif r['status'] == 'pending':
            state = 'Paying · free month on your next payment'
        elif r['status'] == 'capped':
            state = 'Paying · you have earned the most free months'
        elif r['status'] == 'reversed':
            state = 'Refunded'
        else:
            state = 'Paying'
        if r and r['status'] != 'reversed':
            out['paying'] += 1
        out['rows'].append({'name': o.get('name') or o['slug'], 'state': state})
    out['months'] = sum(1 for r in rewards.values() if r['status'] in LIVE)
    out['waiting'] = sum(1 for r in rewards.values() if r['status'] == 'pending')
    return out


def sender_name(engine, ref):
    """The business that sent this visitor, for the signup page ("Dana's
    Cleaning sent you"), or None when the link names nobody real."""
    ref = (ref or '').strip().lower()
    if not ref:
        return None
    try:
        org = control_plane.find(engine, ref)
    except Exception:
        return None
    if not org or org.get('is_test') or org.get('is_demo'):
        return None
    return org.get('name') or None
