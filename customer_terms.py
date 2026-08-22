"""The service terms customers agree to when they book.

Shown on the booking confirmation, the payment page and every invoice, so the
terms travel with the money rather than living only on a website page nobody
reads. Editable in Settings → Business.

The scope-change clause is the one that matters most in a card dispute: it
says, in advance, that a job materially bigger than quoted gets repriced and
that the card on file covers it. A "no refunds" line alone doesn't help there —
a disputing customer isn't asking for a refund, they're saying they never
authorised the amount.

NOT LEGAL ADVICE. This is a practical starting draft using ordinary industry
terms; have an attorney read it before relying on it in a real fight.
"""

DEFAULT_TERMS = """**Payment terms**

Payment is due in full on the day the cleaning is completed. Invoices are due on
the date they are issued.

**Card on file**

When you pay a deposit or save a card, you authorise us to charge that card for
the remaining balance of your cleaning, including any adjustment made under the
scope-change clause below.

**If the job is bigger than quoted**

Our price is based on the home's size, condition and the service you selected.
If the property turns out to be materially different from what was described —
heavier soiling, additional rooms, hoarding, post-construction debris, pet
damage, or a size larger than stated — we will contact you with a revised price
before or during the visit. Continuing the service after we notify you, or
being unreachable while our cleaners are on site, constitutes acceptance of the
revised price, and the card on file may be charged for it.

**Services already performed are non-refundable**

Cleaning is a service, not a product. Once the work has been performed it cannot
be returned, and payment for completed work is non-refundable.

**If you're not happy — tell us first**

We would much rather fix it than argue about it. If something was missed, contact
us within 24 hours of the cleaning and we will return and re-clean the affected
areas at no charge. This is your remedy for an unsatisfactory clean.

**Damage, wear and fragile items**

We treat every home with care. If we break something through our own
carelessness, tell us within 24 hours of the cleaning and we will put it right.

Cleaning does, however, put ordinary contact on things that are already failing,
and we are not responsible for:

- Items that were already broken, cracked, loose, worn, or poorly fitted and
  that give way during normal cleaning. Blinds, towel rails, toilet seats,
  shelving, curtain rods, cabinet handles and similar fittings are the usual
  examples.
- Damage caused by a defect, an earlier repair, or an installation we had no way
  of knowing about.
- Deterioration that cleaning reveals rather than causes — finishes lifting,
  grout or caulk failing, or discolouration found under an appliance, rug or
  ornament.

Please put away or point out anything valuable, fragile or temperamental before
we arrive — heirlooms, art, collectibles, electronics, and loose cash or
jewellery especially. Tell us and we will work around it or leave it untouched.
If you know something is already loose or on its last legs, say so and we will
not touch it.

**Our cleaners**

The cleaners we send are part of our team, and you are introduced to them
through us rather than on your own. For 24 months after your last cleaning with
us, please do not hire or pay any of our cleaners directly, or through another
company, for work of the kind we provide.

If you and a cleaner would genuinely like to work together directly, we can
usually arrange it. It requires our written approval and a $2,000 release fee,
agreed in advance as a fair estimate of what losing that relationship costs us.

**Cancellations and lockouts**

Cancel at least 24 hours before your appointment at no charge. Cancellations
inside 24 hours, lockouts, or being unable to access the property on arrival are
charged at 50% of the booking, to cover the cleaner's reserved time and travel.

**Chargebacks**

Please contact us before disputing a charge. We keep records of the work
performed, including before-and-after photographs and the time our cleaners were
on site, and we will provide them to your card issuer.
"""


def get_terms():
    from models import BusinessSetting
    return (BusinessSetting.get('customer_terms') or '').strip() or DEFAULT_TERMS


def as_html():
    """Render the terms for an email or page. Deliberately tiny — the terms are
    plain text with **bold** headings, not a markup language."""
    import html as _html
    out = []
    for block in get_terms().split('\n\n'):
        block = block.strip()
        if not block:
            continue
        safe = _html.escape(block)
        if safe.startswith('**') and safe.endswith('**'):
            out.append(f'<p style="font-weight:700;margin:14px 0 4px">{safe.strip("*")}</p>')
        else:
            out.append(f'<p style="margin:0 0 8px;line-height:1.6">{safe}</p>')
    return '\n'.join(out)


def record_acceptance(booking, request=None):
    """Snapshot the terms a customer agreed to, at the moment they paid.

    Storing a reference to "our terms" is worth nothing in a dispute months
    later — terms get edited, and the bank has no way to know what they said on
    the day. So the wording itself is kept, with the time and the IP address it
    was accepted from.

    Only the first acceptance is kept. A customer who pays a deposit and then a
    balance agreed at the earlier moment, and that is the one that matters."""
    from extensions import db
    from datetime import datetime
    if booking.terms_accepted_at:
        return False
    booking.terms_accepted_at = datetime.utcnow()
    booking.terms_accepted_text = get_terms()
    if request is not None:
        forwarded = (request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        booking.terms_accepted_ip = (forwarded or request.remote_addr or '')[:64]
    db.session.commit()
    return True
