"""Invoices — owner list + public, branded, itemized invoice page. Payment reuses
the booking's existing pay flow. See invoicing.py for the engine."""
from flask import Blueprint, render_template, request
from auth import login_required
from models import Booking, BusinessSetting
import invoicing
import branding

invoices_bp = Blueprint('invoices', __name__)


def _biz():
    return {
        'name': branding.biz_name(),
        'phone': BusinessSetting.get('phone') or '',
        'email': BusinessSetting.get('email') or '',
        'address': BusinessSetting.get('address') or '',
        'city': BusinessSetting.get('city') or '',
    }


@invoices_bp.route('/invoices/')
@login_required
def index():
    from blueprints.payments import amount_due
    invs = Booking.query.filter(Booking.invoice_number.isnot(None)) \
                        .order_by(Booking.invoice_issued_at.desc()).all()
    rows = [{'b': b, 'status': invoicing.status(b), 'due': amount_due(b)} for b in invs]
    counts = {'all': len(invs)}
    for s in ('sent', 'overdue', 'paid', 'draft'):
        counts[s] = sum(1 for r in rows if r['status'] == s)
    sf = request.args.get('status', '')
    if sf:
        rows = [r for r in rows if r['status'] == sf]
    return render_template('admin/invoices.html', rows=rows, counts=counts,
                           status_filter=sf, status_labels=invoicing.STATUS_LABELS)


@invoices_bp.route('/invoice/<token>')
def view(token):
    b = Booking.query.filter_by(pay_token=token).first_or_404()
    from blueprints.payments import amount_due, payment_link_url
    import customer_terms
    return render_template('public/invoice.html', b=b, biz=_biz(),
                           items=invoicing.line_items(b), due=amount_due(b),
                           terms=customer_terms.as_html(),
                           status=invoicing.status(b), pay_url=payment_link_url(b, 'full'))
