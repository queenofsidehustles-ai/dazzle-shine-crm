"""Bookkeeping: expenses in, profit out.

The ledger the owner types into, plus the P&L that nets it against everything
the CRM already knows it paid. Owner-only — this is the money.
"""
import csv
import io
import os
from datetime import date, datetime

from flask import (Blueprint, Response, flash, redirect, render_template,
                   request, url_for)

import finance
import stripe_fees
from auth import owner_required
from extensions import db
from models import (AUTO_CATEGORIES, EXPENSE_CATEGORIES, IRS_MILEAGE_RATE,
                    BusinessSetting, Expense, RecurringExpense)

money_bp = Blueprint('money', __name__, url_prefix='/money')

VALID_CATEGORIES = {k for k, _l, _g, _s in EXPENSE_CATEGORIES}


def _cloudinary():
    return (os.environ.get('CLOUDINARY_CLOUD_NAME', 'dasgvqtyk'),
            os.environ.get('CLOUDINARY_UPLOAD_PRESET', 'dazzle_interviews'))


def _period_from_request():
    """(kind, year, month) from the query string, defaulting to this month."""
    today = date.today()
    kind = request.args.get('period', 'month')
    if kind not in ('month', 'quarter', 'year'):
        kind = 'month'
    try:
        year = int(request.args.get('year', today.year))
        month = int(request.args.get('month', today.month))
    except ValueError:
        year, month = today.year, today.month
    month = min(12, max(1, month))
    return kind, year, month


def _amount_from_form(form):
    """Mileage entries are logged as a trip; everything else as a dollar amount.
    Returns (amount, miles, rate) or (None, err, None)."""
    category = form.get('category', '')
    if category == 'mileage':
        try:
            miles = float(form.get('miles') or 0)
            rate = float(form.get('rate_per_mile') or IRS_MILEAGE_RATE)
        except ValueError:
            return None, 'Enter the miles driven as a number.', None
        if miles <= 0:
            return None, 'Enter how many miles you drove.', None
        return round(miles * rate, 2), miles, rate
    try:
        amount = float(form.get('amount') or 0)
    except ValueError:
        return None, 'Enter the amount as a number, like 49.99.', None
    if amount <= 0:
        return None, 'Enter an amount greater than zero.', None
    return round(amount, 2), None, None


# ── Expense ledger ──────────────────────────────────────────────────────────
@money_bp.route('/expenses')
@owner_required
def expenses():
    kind, year, month = _period_from_request()
    start, end, label = finance.period_bounds(kind, year, month)
    rows = finance.expenses_between(start, end)
    total = round(sum(e.amount or 0 for e in rows), 2)
    cloud_name, preset = _cloudinary()
    return render_template('admin/expenses.html',
        expenses=rows, total=total, period_label=label,
        kind=kind, year=year, month=month, today=date.today().isoformat(),
        categories=EXPENSE_CATEGORIES, mileage_rate=IRS_MILEAGE_RATE,
        cloud_name=cloud_name, upload_preset=preset,
        recurring=RecurringExpense.query.order_by(RecurringExpense.active.desc(),
                                                  RecurringExpense.vendor).all())


@money_bp.route('/expenses/add', methods=['POST'])
@owner_required
def add_expense():
    back = redirect(url_for('money.expenses', period=request.form.get('kind', 'month'),
                            year=request.form.get('year'), month=request.form.get('month')))
    category = request.form.get('category', '')
    if category in AUTO_CATEGORIES:
        flash(f'{AUTO_CATEGORIES[category]} is totalled automatically from your own records — '
              f'adding it by hand would count it twice.', 'error')
        return back
    if category not in VALID_CATEGORIES:
        flash('Pick a category for this expense.', 'error')
        return back

    amount, miles, rate = _amount_from_form(request.form)
    if amount is None:
        flash(miles, 'error')          # the error message rides in the 2nd slot
        return back

    e = Expense(
        date=request.form.get('date') or date.today().isoformat(),
        category=category, amount=amount, miles=miles, rate_per_mile=rate,
        vendor=(request.form.get('vendor') or '').strip() or None,
        note=(request.form.get('note') or '').strip() or None,
        method=request.form.get('method') or None,
        receipt_url=(request.form.get('receipt_url') or '').strip() or None,
    )
    db.session.add(e)
    db.session.commit()
    what = f'{miles:g} miles' if miles else f'${amount:.2f}'
    flash(f'Logged {what} — {e.category_label}.', 'success')
    return back


@money_bp.route('/expenses/<int:expense_id>/edit', methods=['POST'])
@owner_required
def edit_expense(expense_id):
    e = Expense.query.get_or_404(expense_id)
    back = redirect(url_for('money.expenses', period=request.form.get('kind', 'month'),
                            year=request.form.get('year'), month=request.form.get('month')))
    category = request.form.get('category', e.category)
    if category in AUTO_CATEGORIES or category not in VALID_CATEGORIES:
        flash('That category can\'t be used for a hand-entered expense.', 'error')
        return back
    e.category = category
    amount, miles, rate = _amount_from_form(request.form)
    if amount is None:
        flash(miles, 'error')
        return back
    e.amount, e.miles, e.rate_per_mile = amount, miles, rate
    e.date = request.form.get('date') or e.date
    e.vendor = (request.form.get('vendor') or '').strip() or None
    e.note = (request.form.get('note') or '').strip() or None
    e.method = request.form.get('method') or None
    if request.form.get('receipt_url'):
        e.receipt_url = request.form['receipt_url'].strip()
    db.session.commit()
    flash('Expense updated.', 'success')
    return back


@money_bp.route('/expenses/<int:expense_id>/delete', methods=['POST'])
@owner_required
def delete_expense(expense_id):
    e = Expense.query.get_or_404(expense_id)
    label, amount = e.category_label, e.amount or 0
    db.session.delete(e)
    db.session.commit()
    flash(f'Deleted ${amount:.2f} — {label}.', 'success')
    return redirect(url_for('money.expenses', period=request.form.get('kind', 'month'),
                            year=request.form.get('year'), month=request.form.get('month')))


# ── Recurring costs ─────────────────────────────────────────────────────────
@money_bp.route('/recurring/add', methods=['POST'])
@owner_required
def add_recurring():
    back = redirect(url_for('money.expenses'))
    category = request.form.get('category', '')
    if category in AUTO_CATEGORIES or category not in VALID_CATEGORIES:
        flash('Pick a category for this recurring cost.', 'error')
        return back
    try:
        amount = round(float(request.form.get('amount') or 0), 2)
        day = min(28, max(1, int(request.form.get('day_of_month') or 1)))
    except ValueError:
        flash('Enter the amount and day as numbers.', 'error')
        return back
    if amount <= 0:
        flash('Enter an amount greater than zero.', 'error')
        return back
    r = RecurringExpense(
        category=category, amount=amount, day_of_month=day, active=True,
        vendor=(request.form.get('vendor') or '').strip() or None,
        note=(request.form.get('note') or '').strip() or None,
        method=request.form.get('method') or None,
    )
    db.session.add(r)
    db.session.commit()
    flash(f'${amount:.2f} to {r.vendor or r.category_label} will post on day {day} every month.',
          'success')
    return back


@money_bp.route('/recurring/<int:rec_id>/toggle', methods=['POST'])
@owner_required
def toggle_recurring(rec_id):
    r = RecurringExpense.query.get_or_404(rec_id)
    r.active = not r.active
    db.session.commit()
    flash(f'{r.vendor or r.category_label} {"resumed" if r.active else "paused"}.', 'success')
    return redirect(url_for('money.expenses'))


@money_bp.route('/recurring/<int:rec_id>/delete', methods=['POST'])
@owner_required
def delete_recurring(rec_id):
    r = RecurringExpense.query.get_or_404(rec_id)
    name = r.vendor or r.category_label
    # Expenses it already posted stay — they really happened.
    Expense.query.filter_by(recurring_id=r.id).update({'recurring_id': None})
    db.session.delete(r)
    db.session.commit()
    flash(f'{name} removed. Costs it already posted were kept.', 'success')
    return redirect(url_for('money.expenses'))


def post_due_recurring(today=None):
    """Post any monthly cost whose day has arrived and that hasn't posted this
    month. Idempotent — the last_posted stamp is the guard. Returns how many."""
    today = today or date.today()
    stamp = today.strftime('%Y-%m')
    posted = 0
    for r in RecurringExpense.query.filter_by(active=True).all():
        if r.last_posted == stamp:
            continue
        if today.day < (r.day_of_month or 1):
            continue                     # not due yet this month
        on = date(today.year, today.month, min(r.day_of_month or 1, 28))
        db.session.add(Expense(
            date=on.isoformat(), category=r.category, amount=r.amount,
            vendor=r.vendor, note=r.note, method=r.method, recurring_id=r.id))
        r.last_posted = stamp
        posted += 1
    if posted:
        db.session.commit()
    return posted


@money_bp.route('/recurring/run', methods=['POST'])
@owner_required
def run_recurring():
    n = post_due_recurring()
    flash(f'Posted {n} recurring cost{"s" if n != 1 else ""}.' if n
          else 'Nothing due to post right now.', 'success')
    return redirect(url_for('money.expenses'))


# ── Profit & Loss ───────────────────────────────────────────────────────────
@money_bp.route('/pnl')
@owner_required
def pnl():
    kind, year, month = _period_from_request()
    start, end, label = finance.period_bounds(kind, year, month)
    data = finance.profit_and_loss(start, end)
    trend = finance.monthly_trend(6)
    return render_template('admin/pnl.html', p=data, period_label=label,
        kind=kind, year=year, month=month,
        trend_labels=[t['month'] for t in trend],
        trend_revenue=[t['revenue'] for t in trend],
        trend_profit=[t['profit'] for t in trend],
        stripe_ready=stripe_fees.is_configured())


@money_bp.route('/pnl/sync-fees', methods=['POST'])
@owner_required
def sync_fees():
    kind, year, month = _period_from_request()
    start, end, _label = finance.period_bounds(kind, year, month)
    done, errors = stripe_fees.sync_months(finance.months_in(start, end))
    if done:
        flash(f'Pulled card fees for {done} month{"s" if done != 1 else ""} from Stripe.', 'success')
    for err in errors[:3]:
        flash(f'Could not sync {err}', 'warning')
    return redirect(url_for('money.pnl', period=kind, year=year, month=month))


@money_bp.route('/jobs')
@owner_required
def job_economics():
    """Which jobs make money, what discounting costs, and what each cleaner is
    really earning per hour."""
    kind, year, month = _period_from_request()
    start, end, label = finance.period_bounds(kind, year, month)
    return render_template('admin/job_economics.html',
        e=finance.job_economics(start, end), period_label=label,
        kind=kind, year=year, month=month)


@money_bp.route('/pnl/export')
@owner_required
def export_csv():
    """Everything in the period as one CSV, with the Schedule C line on each row
    so it can go straight to whoever does the taxes."""
    kind, year, month = _period_from_request()
    start, end, label = finance.period_bounds(kind, year, month)
    p = finance.profit_and_loss(start, end)

    buf = io.StringIO()
    w = csv.writer(buf)
    # White-label: the business name comes from settings, never hardcoded.
    w.writerow([f'{BusinessSetting.get("business_name", "Profit & Loss")} — Profit & Loss', label])
    w.writerow(['Basis', 'Cash — income counted when payment was received'])
    w.writerow([])
    w.writerow(['Date', 'Type', 'Category', 'Schedule C', 'Vendor', 'Note', 'Amount'])

    w.writerow([f'{start} to {end}', 'INCOME', 'Jobs paid', 'Line 1 — Gross receipts',
                '', f"{p['jobs_paid']} job(s)", f"{p['revenue']:.2f}"])
    if p['contractor_pay']:
        w.writerow([f'{start} to {end}', 'EXPENSE', 'Cleaner pay',
                    'Line 11 — Contract labor', '', 'From payroll records',
                    f"-{p['contractor_pay']:.2f}"])
    if p['processing_fees']:
        w.writerow([f'{start} to {end}', 'EXPENSE', 'Card processing fees',
                    'Line 27a — Other', 'Stripe', 'Synced from Stripe',
                    f"-{p['processing_fees']:.2f}"])
    if p['commissions']:
        w.writerow([f'{start} to {end}', 'EXPENSE', 'VA commissions',
                    'Line 11 — Contract labor', '', 'From commission payouts',
                    f"-{p['commissions']:.2f}"])
    for e in p['expenses']:
        note = e.note or ''
        if e.is_mileage:
            note = (note + f' ({e.miles:g} mi @ ${e.rate_per_mile:.2f})').strip()
        w.writerow([e.date, 'EXPENSE', e.category_label, e.schedule_c,
                    e.vendor or '', note, f"-{(e.amount or 0):.2f}"])

    w.writerow([])
    w.writerow(['', '', '', '', '', 'TOTAL INCOME', f"{p['revenue']:.2f}"])
    w.writerow(['', '', '', '', '', 'TOTAL EXPENSES', f"-{p['total_out']:.2f}"])
    w.writerow(['', '', '', '', '', 'NET PROFIT', f"{p['net_profit']:.2f}"])

    fname = f"dazzle-shine-pnl-{label.replace(' ', '-').lower()}.csv"
    return Response(buf.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={fname}'})
