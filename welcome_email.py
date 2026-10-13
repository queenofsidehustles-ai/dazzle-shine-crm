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

  {% if confirm_code %}
  <div style="border:2px solid #D98A2B;border-radius:12px;padding:18px 22px;margin:22px 0">
    <div style="font-weight:700;margin-bottom:6px">First, one quick check that this email reaches you</div>
    <div style="font-size:.95rem;color:#3d4f57">Type this code where your dashboard asks for it:</div>
    <div style="font-size:1.9rem;font-weight:800;letter-spacing:.28em;margin:10px 0 12px">{{ confirm_code }}</div>
    <a href="{{ confirm_url }}" style="color:#13232a;font-weight:600;font-size:.95rem">Or tap here and press &ldquo;Yes, this is me&rdquo; &rarr;</a>
  </div>
  {% endif %}

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

  {{ video|safe }}

  <p style="margin:26px 0">
    <a href="{{ url }}" style="background:#D98A2B;color:#fff;padding:14px 30px;border-radius:999px;text-decoration:none;font-weight:700;display:inline-block">Open my CRM</a>
  </p>

  <p>You are on the top plan while you try it. Your fourteen days start once you add
     one cleaner and one customer — not today — and there is no card on file. When it ends you drop to
     the free plan and <strong>keep everything you entered</strong>.</p>

  <p style="margin-top:24px">Reply to this email if anything is confusing or broken. It
     comes straight to me.</p>

  <p style="color:#55686f;font-size:.9rem;margin-top:28px">
     {{ product_name }} — pronounced &ldquo;ah-CHEH,&rdquo; means &ldquo;good morning.&rdquo;
  </p>
</div>
"""


def build(biz, owner_email, host, first=None, confirm_code=None,
          confirm_url=None):
    import funnel_videos
    url = host if host.startswith('http') else f'https://{host}'
    return render_template_string(
        BODY, biz=biz, email=owner_email, host=host.replace('https://', ''),
        url=url, first=(first or '').strip(), product_name=product.name(),
        confirm_code=confirm_code, confirm_url=confirm_url,
        video=funnel_videos.email_block('signup'))


def send(biz, owner_email, host, first=None, confirm_code=None,
         confirm_url=None):
    """Returns (ok, detail). Never raises: a welcome email that fails must not
    be the reason a signup looks broken to somebody who just succeeded."""
    import notifications
    try:
        return notifications.send_email(
            to_email=owner_email, to_name=biz,
            subject=f'{biz} is set up — here is your address',
            html=build(biz, owner_email, host, first, confirm_code,
                       confirm_url),
            from_name=product.name(),
            from_email=product.from_email() or None,
            reply_to=product.support_email() or None,
            api_key=product.resend_api_key() or None)
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'
