"""The page a quoted customer lands on from their email.

Public and unauthenticated — the token in the URL is the only thing that
identifies them, exactly as the deposit and invoice pages already work.

Its whole reason for existing is the price. Sending someone to the general
booking link means sending them to a calculator, and a calculator can produce a
different number from the one they were told on the phone. Here the figure is
read off the quote and carried straight into the booking.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   abort, flash)
from models import Lead
import quoting

quote_accept_bp = Blueprint('quote_accept', __name__)


@quote_accept_bp.route('/quote/<token>')
def view(token):
    lead = Lead.query.filter_by(quote_token=token).first_or_404()
    return render_template(
        'public/quote_accept.html',
        lead=lead,
        checklist=quoting.checklist_for(lead),
        deposit=_deposit(),
        balance=max(0.0, (lead.quoted_price or 0) - _deposit()),
        # The same wording the quote email carries, from the same place, so the
        # page and the email can't come to promise different numbers of visits.
        scope_note=quoting.scope_note(lead),
        already=lead.status == 'converted',
    )


@quote_accept_bp.route('/quote/<token>/book', methods=['POST'])
def book(token):
    lead = Lead.query.filter_by(quote_token=token).first_or_404()
    if lead.status == 'converted':
        # They already booked from this link. Sending them round again would
        # make a second booking and ask for a second deposit.
        flash('You have already booked with this quote.', 'warning')
        return redirect(url_for('quote_accept.view', token=token))

    when = (request.form.get('preferred_date') or '').strip()
    if not when:
        flash('Please choose a date for your cleaning.', 'warning')
        return redirect(url_for('quote_accept.view', token=token))

    booking = quoting.accept_quote(
        lead,
        preferred_date=when,
        preferred_time=(request.form.get('preferred_time') or '').strip(),
        address=(request.form.get('address') or '').strip(),
        city=(request.form.get('city') or '').strip(),
        zip_code=(request.form.get('zip_code') or '').strip(),
        notes=(request.form.get('notes') or '').strip(),
    )
    # Straight into the deposit flow that already exists — which takes the $50,
    # records the terms they accept by paying, and sends the receipt.
    return redirect(url_for('deposit.pay_deposit_page', token=booking.deposit_token))


def _deposit():
    from pricing import get_deposit
    return float(get_deposit())
