"""The emails Akye sends to its affiliate partners, in one place.

Two, both transactional: the sign-in link, and a note that a payout was sent.
Separate from `trial_nudges.py` (owners) and `lead_nurture.py` (leads) because
a partner is neither, and kept out of any sequence: nothing here is marketing,
so nothing here has a switch. They are listed in the console's Communications
page so they can be previewed and their history read.

Sent as the product (never as a cleaning company), with the product's own key.
"""
import product


def _first(name):
    return (name or '').strip().split(' ')[0] or 'there'


def _frame(partner, body, cta, href):
    return f"""<div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:auto;color:#16213a;line-height:1.6">
  <p>Hi {_first(partner.get('name'))},</p>
  {body}
  <p style="margin:26px 0"><a href="{href}" style="background:#D98A2B;color:#fff;padding:13px 28px;border-radius:999px;text-decoration:none;font-weight:700;display:inline-block">{cta}</a></p>
  <p style="color:#6b7590;font-size:14px">Questions? Reply to this email and a person reads it.</p>
</div>"""


def login_email(partner, url):
    """(subject, html): the one-time sign-in link."""
    name = product.name()
    return (f'Your {name} partner page', _frame(
        partner,
        f'<p>Here is your sign-in link for your {name} partner page. It works once, '
        f'for the next hour.</p>',
        'Open my partner page', url) + '<p style="color:#6b7590;font-size:14px;max-width:520px;margin:auto">If you did not ask for this, ignore it. Nothing happens until the link is used.</p>')


def payout_email(partner, amount_text, reference, url):
    """(subject, html): a payout was sent."""
    name = product.name()
    return (f'{name} sent you {amount_text}', _frame(
        partner,
        f'<p>We just sent <strong>{amount_text}</strong> to your bank through Stripe. '
        f'It usually lands in a day or two.</p>'
        f'<p style="color:#6b7590;font-size:14px">Reference {reference or "—"}. '
        f'The details are on your partner page.</p>',
        'See my payments', url))


def deliver(partner, subject, html, kind, engine=None):
    """Send and write it down. Returns (ok, detail); never raises."""
    import control_plane
    import notifications
    import provisioning
    try:
        ok, detail = notifications.send_email(
            partner['email'], partner['name'], subject, html,
            from_name=product.name(), from_email=product.from_email() or None,
            reply_to=product.support_email() or None,
            api_key=product.resend_api_key() or None)
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f'{type(e).__name__}: {e}'
    control_plane.record_product_message(
        engine or provisioning._engine(), None, kind, partner['email'], subject,
        ok, detail, sent_by='auto')
    return ok, detail
