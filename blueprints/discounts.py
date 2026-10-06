from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from entitlements import requires_plan
from auth import login_required
from models import DiscountCode
from extensions import db

discounts_bp = Blueprint('discounts', __name__, url_prefix='/discounts')


@discounts_bp.route('/')
@login_required
@requires_plan('discounts')
def index():
    codes = DiscountCode.query.order_by(DiscountCode.created_at.desc()).all()
    return render_template('admin/discounts.html', codes=codes)


@discounts_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        expires_raw = request.form.get('expires_at', '').strip()
        expires = datetime.strptime(expires_raw, '%Y-%m-%d') if expires_raw else None
        max_uses_raw = request.form.get('max_uses', '').strip()
        c = DiscountCode(
            code=request.form['code'].strip().upper(),
            discount_type=request.form.get('discount_type', 'percent'),
            discount_value=float(request.form.get('discount_value', 0)),
            max_uses=int(max_uses_raw) if max_uses_raw else None,
            expires_at=expires,
            is_active=True,
        )
        db.session.add(c)
        db.session.commit()
        flash(f'Code {c.code} created!', 'success')
        return redirect(url_for('discounts.index'))
    return render_template('admin/discount_form.html', code=None)


@discounts_bp.route('/<int:code_id>', methods=['GET', 'POST'])
@login_required
def edit(code_id):
    c = DiscountCode.query.get_or_404(code_id)
    if request.method == 'POST':
        expires_raw = request.form.get('expires_at', '').strip()
        max_uses_raw = request.form.get('max_uses', '').strip()
        c.code = request.form['code'].strip().upper()
        c.discount_type = request.form.get('discount_type', 'percent')
        c.discount_value = float(request.form.get('discount_value', 0))
        c.max_uses = int(max_uses_raw) if max_uses_raw else None
        c.expires_at = datetime.strptime(expires_raw, '%Y-%m-%d') if expires_raw else None
        c.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Code updated!', 'success')
        return redirect(url_for('discounts.index'))
    return render_template('admin/discount_form.html', code=c)


@discounts_bp.route('/<int:code_id>/delete', methods=['POST'])
@login_required
def delete(code_id):
    c = DiscountCode.query.get_or_404(code_id)
    db.session.delete(c)
    db.session.commit()
    flash('Code deleted.', 'success')
    return redirect(url_for('discounts.index'))
