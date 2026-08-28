from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import Staff
from extensions import db

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')


def _rate(raw, default):
    """A pay rate typed as '50', '50%' or '$22.50'. A bad value falls back to
    the default rather than 500-ing on someone mid-hire."""
    text = (raw or '').strip().replace('%', '').replace('$', '')
    try:
        return round(float(text), 2) if text else default
    except ValueError:
        return default


@staff_bp.route('/')
@login_required
def index():
    staff = Staff.query.order_by(Staff.is_active.desc(), Staff.name).all()
    return render_template('admin/staff.html', staff=staff)


@staff_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        # Checked here, not in the template. Hiding the button is decoration;
        # the URL is still there and the person most likely to type it is the
        # one who just hit the limit.
        import entitlements
        ok, why = entitlements.check_limit('field_workers')
        if not ok:
            flash(why, 'error')
            return redirect(url_for('billing.upgrade', feature='field_workers'))
        s = Staff(
            name=request.form['name'].strip(),
            phone=request.form.get('phone', '').strip(),
            email=request.form.get('email', '').strip(),
            color=request.form.get('color', '#7c3aed'),
            is_active='is_active' in request.form,
            pay_type=request.form.get('pay_type', 'percent'),
            pay_rate=_rate(request.form.get('pay_rate'), 50.0),
        )
        db.session.add(s)
        db.session.commit()
        flash(f'{s.name} added to the team — they can be assigned jobs now.',
              'success')
        return redirect(url_for('contractors.team'))
    return render_template('admin/staff_form.html', staff=None)


@staff_bp.route('/<int:staff_id>', methods=['GET', 'POST'])
@login_required
def edit(staff_id):
    s = Staff.query.get_or_404(staff_id)
    if request.method == 'POST':
        s.name = request.form['name'].strip()
        s.phone = request.form.get('phone', '').strip()
        s.email = request.form.get('email', '').strip()
        s.color = request.form.get('color', s.color)
        s.is_active = 'is_active' in request.form
        # The form posts these now, so the edit page has to save them — leaving
        # them out would silently revert a rate whenever anything else here was
        # changed.
        s.pay_type = request.form.get('pay_type', s.pay_type)
        s.pay_rate = _rate(request.form.get('pay_rate'), s.pay_rate)
        db.session.commit()
        flash('Team member updated!', 'success')
        return redirect(url_for('contractors.team'))
    return render_template('admin/staff_form.html', staff=s)


@staff_bp.route('/<int:staff_id>/toggle', methods=['POST'])
@login_required
def toggle_active(staff_id):
    """Silently activate/deactivate a team member. Deactivating removes them
    from all job broadcasts, the assignment dropdown, and reminder emails.
    No notification is ever sent to the team member."""
    s = Staff.query.get_or_404(staff_id)
    s.is_active = not s.is_active
    db.session.commit()
    if s.is_active:
        flash(f'{s.name} is active again and can receive job assignments.', 'success')
    else:
        flash(f'{s.name} has been deactivated — they will no longer receive job assignments or notifications.', 'success')
    return redirect(url_for('staff.index'))


@staff_bp.route('/<int:staff_id>/delete', methods=['POST'])
@login_required
def delete(staff_id):
    s = Staff.query.get_or_404(staff_id)
    db.session.delete(s)
    db.session.commit()
    flash('Team member removed.', 'success')
    return redirect(url_for('staff.index'))
