"""The welcome email that gives a recurring client their portal.

Two separate messages, sent at two different moments, because asking a brand-new
customer to hand over card details before you have cleaned for her once is a
worse first impression than the convenience is worth:

  welcome_html()  — sent when she's set up. Here is your schedule, your price,
                    your portal. Saving a card is mentioned as something she
                    *can* do, not something she's being asked to do.

  card_nudge_html() — sent after the first clean is done and paid. Now there's a
                    reason to trust it, so this one actually asks.

Both are plain HTML built from her real booking data, so what the owner previews
is exactly what the customer receives.
"""
from datetime import date

import branding


def _fmt_date(iso):
    """'Wednesday 9 September' — no year, because every visit is soon."""
    try:
        return date.fromisoformat(iso).strftime('%A %-d %B')
    except (ValueError, TypeError):
        return iso or 'your scheduled date'


def _money(v):
    return f'${v:,.2f}'.replace('.00', '')


def _shell(inner, biz):
    accent = '#b98a33'
    return f"""
<div style="font-family:Inter,-apple-system,Segoe UI,sans-serif;max-width:540px;margin:0 auto;color:#1f1333;line-height:1.6">
{inner}
  <p style="color:#9a95ad;font-size:0.8rem;margin:26px 0 0;padding-top:16px;border-top:1px solid #eae6f2">
    {biz}{' · ' + branding.city_line() if branding.city_line() else ''}<br>
    Reply to this email any time — it comes straight to us.
  </p>
</div>"""


def upcoming_visits(client, limit=4):
    """Her next few scheduled cleanings, soonest first."""
    today = date.today().isoformat()
    visits = [b for b in client.bookings
              if b.status != 'cancelled' and (b.preferred_date or '') >= today]
    return sorted(visits, key=lambda b: b.preferred_date or '')[:limit]


def welcome_subject(client):
    return f"You're all set — welcome to {branding.biz_name()}"


def welcome_html(client, portal_url):
    """The first email. Warm, concrete, no ask."""
    biz = branding.biz_name()
    first = (client.name or 'there').split()[0]
    visits = upcoming_visits(client)

    if visits:
        rows = ''.join(
            f'<tr><td style="padding:7px 0;border-bottom:1px solid #f0edf8">{_fmt_date(v.preferred_date)}'
            f'{" · " + v.preferred_time if v.preferred_time else ""}</td>'
            f'<td style="padding:7px 0;border-bottom:1px solid #f0edf8;text-align:right;white-space:nowrap">'
            f'{_money(v.price) if v.price else ""}</td></tr>'
            for v in visits)
        schedule = f"""
  <p style="margin:22px 0 8px;font-weight:700">Your next cleanings</p>
  <table style="width:100%;border-collapse:collapse;font-size:0.95rem">{rows}</table>
  <p style="color:#9a95ad;font-size:0.84rem;margin:8px 0 0">
    Same date every month. We'll remind you before each one.</p>"""
    else:
        schedule = ''

    return _shell(f"""
  <h2 style="color:#b98a33;font-size:1.35rem;margin:0 0 14px">Welcome, {first}!</h2>

  <p style="margin:0 0 14px">Thank you for choosing us — we're really glad to have you.
     Everything's set up on our side, and I've made you a private page where you can see
     your cleanings, your invoices, and anything you've paid.</p>
{schedule}

  <p style="margin:24px 0"><a href="{portal_url}"
     style="background:#d3a84f;color:#1a1225;padding:13px 28px;border-radius:999px;
            text-decoration:none;font-weight:700;display:inline-block">Open your page →</a></p>

  <p style="color:#5f5878;font-size:0.9rem;margin:0 0 14px">
    The link is private to you. The first time you open it we'll ask for your ZIP code
    just to be sure it's you.</p>

  <div style="background:#faf9fd;border-radius:10px;padding:14px 16px;margin:20px 0">
    <p style="margin:0;font-size:0.9rem;color:#5f5878">
      <strong style="color:#1f1333">If you'd like</strong>, you can also save a card on that page and
      we'll take care of payment automatically each month — no invoices to remember.
      Entirely up to you, and you can turn it off whenever you want.</p>
  </div>

  <p style="margin:0">Any questions at all, just reply.</p>
  <p style="margin:14px 0 0">— {biz}</p>
""", biz)


def card_nudge_subject(client):
    return 'Would you like us to handle payment automatically?'


def card_nudge_html(client, portal_url):
    """The second email, after the first clean. Now it asks."""
    biz = branding.biz_name()
    first = (client.name or 'there').split()[0]
    nxt = upcoming_visits(client, limit=1)
    when = f' Your next one is {_fmt_date(nxt[0].preferred_date)}.' if nxt else ''

    return _shell(f"""
  <h2 style="color:#b98a33;font-size:1.3rem;margin:0 0 14px">How did we do, {first}?</h2>

  <p style="margin:0 0 14px">We hope your home felt wonderful to come back to.
     Thank you again for having us.{when}</p>

  <p style="margin:0 0 14px">Since you're on a regular schedule, would you like us to
     <strong>handle payment automatically</strong>? Save a card on your page and we'll charge it
     the morning of each cleaning — nothing to remember, no invoice to chase.</p>

  <p style="margin:24px 0"><a href="{portal_url}"
     style="background:#d3a84f;color:#1a1225;padding:13px 28px;border-radius:999px;
            text-decoration:none;font-weight:700;display:inline-block">Save a card →</a></p>

  <p style="color:#5f5878;font-size:0.9rem;margin:0 0 14px">
    Your card is stored securely by Stripe — we never see the number. You can remove it
    or switch this off yourself at any time, right from the same page.</p>

  <p style="margin:0">Happy to keep invoicing you the usual way if you'd rather. Just say.</p>
  <p style="margin:14px 0 0">— {biz}</p>
""", biz)
