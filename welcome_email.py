"""The email a cleaning company gets when it signs up.

One email, and deliberately only one. A new owner does not need a feature tour
— they need the thing they would otherwise have to remember: the address of
their own CRM. They chose that subdomain ninety seconds ago, saw it once on a
confirmation screen, and if they close the tab there is nothing in their inbox
to search for.

Everything else here earns its place by answering a question somebody actually
has on day one: where do I sign in, which email did I use, what do I do first,
and who do I reply to when something is wrong.
"""
from flask import render_template_string

import product

BODY = """
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;color:#13232a">
  <p style="font-size:1.05rem">Hi{{ ' ' + first if first }},</p>

  <p>{{ biz }} is set up. Everything below is yours — your customers, your cleaners,
     your prices, your money.</p>

  <div style="background:#0D1526;border-radius:12px;padding:22px 24px;margin:22px 0">
    <div style="color:#9fb0c9;font-size:.78rem;letter-spacing:.09em;text-transform:uppercase;font-weight:700;margin-bottom:8px">Your address</div>
    <a href="{{ url }}" style="color:#fff;font-size:1.22rem;font-weight:800;text-decoration:none">{{ host }}</a>
    <div style="color:#9fb0c9;font-size:.9rem;margin-top:10px">Sign in with <strong style="color:#fff">{{ email }}</strong></div>
  </div>

  <p><strong>Bookmark that link.</strong> It is the one thing worth keeping from this
     email — it is your own address, and nobody else can use it.</p>

  <p style="margin-top:22px"><strong>What to do first</strong><br>
     Add one cleaner, one customer and one job. That is the whole loop, and the
     <em>Getting started</em> list on your dashboard walks you through it. Everything
     else — taking card payments, texting your crew, sending invoices — comes after,
     and only when you want it.</p>

  <p style="margin:26px 0">
    <a href="{{ url }}" style="background:#D98A2B;color:#fff;padding:14px 30px;border-radius:999px;text-decoration:none;font-weight:700;display:inline-block">Open my CRM</a>
  </p>

  <p>You are on the top plan while you try it. Your fourteen days start when you assign
     your first job — not today — and there is no card on file. When it ends you drop to
     the free plan and <strong>keep everything you entered</strong>.</p>

  <p style="margin-top:24px">Reply to this email if anything is confusing or broken. It
     comes straight to me.</p>

  <p style="color:#55686f;font-size:.9rem;margin-top:28px">
     {{ product_name }} — pronounced &ldquo;ah-CHEH,&rdquo; means &ldquo;good morning.&rdquo;
  </p>
</div>
"""


def build(biz, owner_email, host, first=None):
    url = host if host.startswith('http') else f'https://{host}'
    return render_template_string(
        BODY, biz=biz, email=owner_email, host=host.replace('https://', ''),
        url=url, first=(first or '').strip(), product_name=product.name())


def send(biz, owner_email, host, first=None):
    """Returns (ok, detail). Never raises: a welcome email that fails must not
    be the reason a signup looks broken to somebody who just succeeded."""
    import notifications
    try:
        return notifications.send_email(
            to_email=owner_email, to_name=biz,
            subject=f'{biz} is set up — here is your address',
            html=build(biz, owner_email, host, first),
            from_name=product.name(),
            from_email=product.from_email() or None,
            reply_to=product.support_email() or None,
            api_key=product.resend_api_key() or None)
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'
