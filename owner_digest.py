"""The morning email version of Nana's pull answers.

daily_plan.py already works out what is worth doing today, computed against
the real database, most costly to ignore first. Nobody reads it until they
open the app, and the owner who signed up for this precisely because they are
not sitting at a screen is the one who never sees it. This is that same list,
pushed to the one place they already check without being asked to: their
inbox, before they have opened anything.

The specificity is the point. "Check your dashboard" is a notification nobody
needs a product for. "3 enquiries waiting on a price, 2 jobs tomorrow with
nobody assigned, $340 owed on finished work" is a business, in one glance,
before coffee. Every line below already has a name or a number in it, because
`daily_plan.items()` refuses to report anything that does not.

## Silent on a quiet day

An email every morning saying "nothing needs you" trains the reply to become
"delete without reading," and the day something actually does need attention
arrives in a mailbox that has stopped looking. So this sends nothing at all
unless `daily_plan.items()` found something real -- the same rule
insurance-expiry and every other quiet automation in this file follows.

## No new numbers

Nothing here is computed twice. Every figure is read once, by daily_plan, and
carried through unchanged. A push channel that quietly drifted from what the
in-app list says would be worse than no push channel at all -- two different
answers to "what needs me today" is how you stop trusting either one.
"""
from html import escape


def _link(path):
    """A full URL a mail client will actually open, not a bare app route."""
    import branding
    base = (branding.crm_base() or '').rstrip('/')
    return f'{base}{path}' if base else path


def compose():
    """(subject, html) for today's digest, or (None, None) if there is
    nothing worth sending. Pure with respect to mail — reads the database,
    sends nothing — so the tests can check the words without a network call.
    """
    import daily_plan
    import branding
    rows = daily_plan.items()
    if not rows:
        return None, None

    first = (branding.owner_email() or '').split('@')[0].split('.')[0].title()
    n = len(rows)
    subject = f'{n} thing{"s" if n != 1 else ""} worth doing today — {rows[0][1][:60]}'

    # Worst-first, exactly as daily_plan ordered them — the one line that
    # would cost the most to ignore is the first thing read on a phone.
    li = []
    for _urgency, text, path in rows:
        li.append(
            f'<li style="margin:0 0 12px;line-height:1.5">'
            f'<a href="{_link(path)}" style="color:#16213a;text-decoration:none">'
            f'{escape(text)}</a></li>')

    html = f'''
<div style="font-family:-apple-system,Segoe UI,Inter,sans-serif;max-width:520px;
            margin:0 auto;color:#16213a;line-height:1.55">
  <p style="font-size:17px;margin:0 0 18px">Morning{", " + first if first else ""} —</p>
  <p style="margin:0 0 16px;color:#5f5878">
    {n} thing{"s" if n != 1 else ""} worth doing today, most important first:
  </p>
  <ul style="padding-left:20px;margin:0 0 24px">
    {''.join(li)}
  </ul>
  <p style="margin:0">
    <a href="{_link('/')}" style="background:#f0a44b;color:#16213a;
       text-decoration:none;font-weight:600;padding:12px 22px;border-radius:8px;
       display:inline-block">Open the dashboard &rarr;</a>
  </p>
  <p style="color:#7a8499;font-size:13px;margin-top:28px;border-top:1px solid #e6eaf2;
            padding-top:14px">
    This is the same list Nana can read back if you ask her "what's next" —
    sent once a day so you do not have to open the app to see it.
  </p>
</div>'''
    return subject, html


def run():
    """Send today's digest to the owner, once. Returns (sent: bool, detail).

    Never sent twice in a day: it is only ever called by the daily cron, the
    same guarantee every other daily job here relies on rather than
    re-deriving — there is no per-send record because there is nothing to
    dedupe against within a single calendar day.
    """
    subject, html = compose()
    if not subject:
        return False, 'nothing worth sending today'

    import branding
    from notifications import send_email
    to = (branding.owner_email() or '').strip()
    if not to or to.endswith('@example.com'):
        try:
            import errors
            errors.capture(
                RuntimeError('owner digest had things to say and no owner '
                             'email to send them to'),
                path='/api/owner-digest', method='POST')
        except Exception:
            pass
        return False, 'no owner email on file'

    ok, detail = send_email(to, branding.biz_name(), subject, html)
    return bool(ok), detail
