"""Is the platform's own background work still happening?

The Health page used to answer "is each company's automation running". It said
nothing about the things that keep the whole product alive and run somewhere a
person is not looking:

    backups            a GitHub Action, every night
    the scheduler      a GitHub Action, every hour and every day
    the product's jobs trial emails and lead nurture, daily
    Stripe's webhook   what turns a payment into a plan

When one of those stops, nothing breaks loudly. A backup that has not run for
a week looks exactly like one that ran last night until the day it is needed.
So each reports in (control_plane.platform_runs) when it finishes, and this
module turns those reports into one of four states:

    ok       reported success recently
    stale    its last success is older than it should be
    failed   its most recent run reported failure
    never    it has not reported yet (new deployment, or not wired up)

`never` is shown but not alarming: the first run after this ships has not
happened yet, and a console that cried wolf on day one would be ignored on
day thirty.

## What counts as recently

Backups nightly, so 36 hours. The scheduler's hourly run, 3 hours; its daily
run, 30. The product's daily jobs, 30. A little over the period, so one
slow or late run is not an alarm and a missed one is.

## Usage is counts, not dollars

Texts, assistant questions and lead searches are counted per company per month
(entitlements.py, assistant.py, setup_assistant.py). Those counts are real and
shown here against each company's limit. What a call costs is the provider's
number, not ours, and is not recorded, so no dollar figure appears.
"""
from datetime import datetime, timedelta

BACKUP_STALE_HOURS = 36
SCHEDULER_STALE_HOURS = {'scheduler:hourly': 3, 'scheduler:daily': 30}
JOB_STALE_HOURS = {'job:trial-nudges': 30, 'job:lead-nurture': 30}
USAGE_WARN = 0.8

LABELS = {
    'backup:akye': 'Akye database, every company',
    'backup:dazzle': 'Dazzle & Shine CRM',
    'scheduler:hourly': 'Scheduler, hourly',
    'scheduler:daily': 'Scheduler, daily',
    'job:trial-nudges': 'Trial emails to owners',
    'job:lead-nurture': 'Emails to leads',
    'stripe:webhook': "Stripe's webhook",
}


def _label(kind):
    return LABELS.get(kind) or kind.replace(':', ' · ')


def run_state(engine, kind, stale_hours, now=None):
    """One background job's state, in a shape the page can draw."""
    import control_plane
    now = now or datetime.utcnow()
    latest = (control_plane.platform_runs_for(engine, kind, 1) or [None])[0]
    last_ok = control_plane.last_ok_platform_run(engine, kind)
    row = {'kind': kind, 'label': _label(kind), 'latest': latest, 'last_ok': last_ok,
           'last_ok_ago': ago(_hours(now, last_ok)) if last_ok else '—',
           'detail': (latest or {}).get('detail') or '', 'count': (latest or {}).get('items'),
           'stale_hours': stale_hours}
    if not latest:
        row.update(state='never', age_hours=None)
    elif not latest['ok']:
        row.update(state='failed', age_hours=_hours(now, latest['at']))
    elif last_ok and stale_hours and (now - last_ok) > timedelta(hours=stale_hours):
        row.update(state='stale', age_hours=_hours(now, last_ok))
    else:
        row.update(state='ok', age_hours=_hours(now, last_ok or latest['at']))
    return row


def _hours(now, then):  # noqa: E302
    return round((now - then).total_seconds() / 3600, 1) if then else None


def ago(hours):
    """'3 hours ago', '2 days ago'."""
    if hours is None:
        return 'never'
    if hours < 1:
        return f'{max(1, int(hours * 60))} min ago'
    if hours < 48:
        h = int(round(hours))
        return f'{h} hour{"" if h == 1 else "s"} ago'
    d = int(hours // 24)
    return f'{d} days ago'


def backups(engine, now=None):
    import control_plane
    kinds = set(control_plane.platform_run_kinds(engine, 'backup:')) | {'backup:akye'}
    return [run_state(engine, k, BACKUP_STALE_HOURS, now) for k in sorted(kinds)]


def scheduler(engine, now=None):
    return [run_state(engine, k, h, now) for k, h in SCHEDULER_STALE_HOURS.items()]


def product_jobs(engine, now=None):
    return [run_state(engine, k, h, now) for k, h in JOB_STALE_HOURS.items()]


def stripe_webhook(engine, now=None):
    """Customer-driven, so never 'stale': only whether the last event worked."""
    return run_state(engine, 'stripe:webhook', None, now)


def platform_errors(engine, limit=10):
    """Unresolved faults recorded outside any company's CRM: the product's own
    pages, the console, the Stripe webhook. ([], 0) if the table is not there.

    Refused cross-site forms ('blocked') are the guard working, not a fault,
    and are left out, as they are on every other error list."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            total = conn.execute(text(
                "select count(*) from public.error_log "
                "where resolved is not true and kind != 'blocked'")).scalar() or 0
            rows = [dict(r) for r in conn.execute(text(
                "select id, kind, message, path, endpoint, count, first_seen, last_seen "
                "from public.error_log where resolved is not true and kind != 'blocked' "
                "order by last_seen desc limit :n"), {'n': limit}).mappings()]
        return rows, total
    except Exception:
        return [], 0


def resolve_platform_errors(engine, error_id=None):
    """Mark platform errors resolved: one by id, or all. A fault that comes back
    is reopened by ErrorLog.record, so this means 'somebody has looked'."""
    from sqlalchemy import text
    with engine.begin() as conn:
        if error_id:
            conn.execute(text("update public.error_log set resolved = true where id = :i"),
                         {'i': int(error_id)})
        else:
            conn.execute(text("update public.error_log set resolved = true "
                              "where resolved is not true and kind != 'blocked'"))


def release():
    try:
        import branding
        return branding.version()
    except Exception:
        return ''


def attention(engine, now=None):
    """Everything that needs a person, cheaply: [{'where', 'text'}]. Used for the
    count on the navigation, so it must stay a handful of small queries."""
    now = now or datetime.utcnow()
    out = []
    for r in backups(engine, now):
        if r['state'] == 'failed':
            out.append({'where': 'Backups', 'text': f'{r["label"]}: the last backup FAILED'})
        elif r['state'] == 'stale':
            out.append({'where': 'Backups', 'text': f'{r["label"]}: last backup {ago(r["age_hours"])}'})
    for r in scheduler(engine, now) + product_jobs(engine, now):
        if r['state'] == 'failed':
            out.append({'where': 'Background jobs', 'text': f'{r["label"]}: the last run failed ({r["detail"] or "no detail"})'})
        elif r['state'] == 'stale':
            out.append({'where': 'Background jobs', 'text': f'{r["label"]}: has not succeeded for {ago(r["age_hours"]).replace(" ago", "")}'})
    hook = stripe_webhook(engine, now)
    if hook['state'] == 'failed':
        out.append({'where': 'Stripe', 'text': f"Stripe's webhook failed on its last event ({hook['detail'] or 'no detail'})"})
    _rows, n = platform_errors(engine, 1)
    if n:
        out.append({'where': 'Errors', 'text': f'{n} unresolved platform error{"" if n == 1 else "s"}'})
    return out


def usage_rows(orgs, snaps):
    """Per-company use of what costs Akye money, against each limit.

    Rows are for companies that have used any of it, busiest first. A limit of
    None is unlimited."""
    import assistant
    import billing
    import entitlements
    import setup_assistant

    def cell(used, limit):
        pct = (used / limit) if limit else 0
        state = 'over' if limit and used >= limit else ('near' if limit and pct >= USAGE_WARN else '')
        return {'used': used, 'limit': limit, 'pct': round(pct * 100), 'state': state}

    rows = []
    for o in orgs:
        s = snaps.get(o['slug'])
        u = (s or {}).get('usage')
        if not s or not s.get('ok') or not u:
            continue
        limits = entitlements.PLANS.get(billing.plan_for(o), {}).get('limits', {})
        r = {'slug': o['slug'], 'name': o.get('name') or o['slug'],
             'plan': billing.plan_for(o),
             'sms': cell(u.get('sms', 0), limits.get('sms_per_month')),
             'nana': cell(u.get('nana', 0), assistant.MONTHLY_LIMIT),
             'setup': cell(u.get('setup_chat', 0), setup_assistant.MONTHLY_LIMIT),
             'searches': cell(u.get('lead_searches', 0), limits.get('lead_searches_per_month'))}
        r['total'] = sum(r[k]['used'] for k in ('sms', 'nana', 'setup', 'searches'))
        r['pressure'] = max(r[k]['pct'] for k in ('sms', 'nana', 'setup', 'searches'))
        if r['total']:
            rows.append(r)
    rows.sort(key=lambda r: (-r['pressure'], -r['total'], r['name']))
    totals = {k: sum(r[k]['used'] for r in rows) for k in ('sms', 'nana', 'setup', 'searches')}
    return rows, totals


def build(engine, orgs, snaps, now=None):
    """Everything the Health page's platform section shows."""
    import platform_switches
    now = now or datetime.utcnow()
    errs, n_errs = platform_errors(engine)
    rows, totals = usage_rows(orgs, snaps)
    problems = attention(engine, now)
    for r in rows:
        if r['pressure'] >= 100:
            problems.append({'where': 'Usage', 'text': f'{r["name"]} has reached a monthly limit'})
    return {'backups': backups(engine, now), 'scheduler': scheduler(engine, now),
            'jobs': product_jobs(engine, now), 'stripe': stripe_webhook(engine, now),
            'errors': errs, 'error_total': n_errs,
            'usage': rows, 'usage_totals': totals,
            'switches': platform_switches.states(engine),
            'release': release(), 'problems': problems, 'ago': ago}
