"""VA commission report + rate settings (owner-only). See va_commission.py for the
calculation engine."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from entitlements import requires_plan
from auth import owner_required
from extensions import db
from models import User, PricingSetting, CommissionPayment
import va_commission as vc

commissions_bp = Blueprint('commissions', __name__, url_prefix='/commissions')


@commissions_bp.route('/')
@owner_required
@requires_plan('va_commissions')
def index():
    vas = User.query.filter_by(role='team').order_by(User.name).all()
    agent = request.args.get('agent', '')
    if not agent and vas:
        agent = vas[0].name
    now = datetime.utcnow()
    try:
        year, month = (int(x) for x in request.args.get('month', '').split('-'))
    except Exception:
        year, month = now.year, now.month
    report = vc.commission_for_month(agent, year, month)
    paid = CommissionPayment.query.filter_by(agent=agent, year=year, month=month).first()
    return render_template('admin/commissions.html', report=report, vas=vas,
                           agent=agent, month_str=f'{year:04d}-{month:02d}',
                           year=year, month=month, paid=paid)


@commissions_bp.route('/mark-paid', methods=['POST'])
@owner_required
def mark_paid():
    """Record that a VA's commission for a month actually went out. That turns a
    calculated figure into a real expense the P&L can subtract — and the one
    record per agent-month keeps it from being double-counted."""
    agent = (request.form.get('agent') or '').strip()
    try:
        year = int(request.form['year'])
        month = int(request.form['month'])
        amount = round(float(request.form.get('amount') or 0), 2)
    except (KeyError, ValueError):
        flash('Could not read that commission payment.', 'error')
        return redirect(url_for('commissions.index'))

    back = redirect(url_for('commissions.index', agent=agent, month=f'{year:04d}-{month:02d}'))
    if not agent:
        flash('Pick a team member first.', 'error')
        return back
    if amount <= 0:
        flash('There is no commission to pay for that month.', 'warning')
        return back

    existing = CommissionPayment.query.filter_by(agent=agent, year=year, month=month).first()
    if existing:
        flash(f'{agent}\'s {year}-{month:02d} commission was already recorded as paid '
              f'on {existing.paid_at.strftime("%b %d, %Y")}.', 'warning')
        return back

    db.session.add(CommissionPayment(
        agent=agent, year=year, month=month, amount=amount,
        method=request.form.get('method', 'zelle'),
        note=f'{agent} commission {year}-{month:02d}'))
    db.session.commit()
    flash(f'Recorded ${amount:.2f} paid to {agent}. It now shows in your Profit & Loss.', 'success')
    return back


@commissions_bp.route('/unmark-paid/<int:payment_id>', methods=['POST'])
@owner_required
def unmark_paid(payment_id):
    p = CommissionPayment.query.get_or_404(payment_id)
    agent, year, month = p.agent, p.year, p.month
    db.session.delete(p)
    db.session.commit()
    flash(f'Undone — {agent}\'s {year}-{month:02d} commission is no longer marked paid.', 'success')
    return redirect(url_for('commissions.index', agent=agent, month=f'{year:04d}-{month:02d}'))


@commissions_bp.route('/settings', methods=['GET', 'POST'])
@owner_required
def settings():
    if request.method == 'POST':
        for key in vc.DEFAULT_RATES:
            v = request.form.get(key)
            if v not in (None, ''):
                PricingSetting.set(key, v)
        db.session.commit()
        flash('Commission rates updated. 💵', 'success')
        return redirect(url_for('commissions.settings'))
    return render_template('admin/commission_settings.html', rates=vc.get_rates())
