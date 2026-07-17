"""VA commission report + rate settings (owner-only). See va_commission.py for the
calculation engine."""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import owner_required
from extensions import db
from models import User, PricingSetting
import va_commission as vc

commissions_bp = Blueprint('commissions', __name__, url_prefix='/commissions')


@commissions_bp.route('/')
@owner_required
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
    return render_template('admin/commissions.html', report=report, vas=vas,
                           agent=agent, month_str=f'{year:04d}-{month:02d}')


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
