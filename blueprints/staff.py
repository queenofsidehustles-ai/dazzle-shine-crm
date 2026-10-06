from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import owner_required
from models import Staff
from extensions import db

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')


def _name_taken(name, exclude_id=None):
    """Is another team member already using this name?

    A solo job records its cleaner as a NAME (`Booking.assigned_cleaner`), and
    payroll finds her again with a case-insensitive name lookup that takes the
    first match. Two cleaners called Maria therefore share one pay history, and
    whichever row comes back first is paid for the other's work. Until
    assignment carries a staff id, distinct names are what keeps the money
    straight.
    """
    q = Staff.query.filter(db.func.lower(Staff.name) == (name or '').strip().lower())
    if exclude_id is not None:
        q = q.filter(Staff.id != exclude_id)
    return q.first()


def _rename_assigned_jobs(old_name, new_name):
    """Carry a rename onto the jobs that name is standing in for.

    Renaming a cleaner used to orphan every solo job assigned to her: the
    booking kept the old string, payroll matched on the new one, and the work
    she had done but not been paid for vanished off the only screen that could
    pay her. Crew rows are keyed by staff id and need nothing.

    Only ever called when the old name was unambiguous — moving jobs when two
    people shared it would hand one cleaner the other's wages.
    """
    from models import Booking
    stale = (Booking.query
             .filter(db.func.lower(Booking.assigned_cleaner) == old_name.lower())
             .all())
    for b in stale:
        b.assigned_cleaner = new_name
    return len(stale)


def _rate(raw, default):
    """A pay rate typed as '50', '50%' or '$22.50'. A bad value falls back to
    the default rather than 500-ing on someone mid-hire."""
    text = (raw or '').strip().replace('%', '').replace('$', '')
    try:
        return round(float(text), 2) if text else default
    except ValueError:
        return default


@staff_bp.route('/')
@owner_required
def index():
    staff = Staff.query.order_by(Staff.is_active.desc(), Staff.name).all()
    return render_template('admin/staff.html', staff=staff)


@staff_bp.route('/new', methods=['GET', 'POST'])
@owner_required
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
        new_name = request.form['name'].strip()
        clash = _name_taken(new_name)
        if clash:
            flash(f'You already have a team member called {clash.name}. '
                  f'Give this one a surname or an initial — a solo job records '
                  f'its cleaner by name, so two the same get paid for each '
                  f"other's work.", 'error')
            return render_template('admin/staff_form.html', staff=None)
        s = Staff(
            name=new_name,
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
@owner_required
def edit(staff_id):
    s = Staff.query.get_or_404(staff_id)
    if request.method == 'POST':
        old_name = (s.name or '').strip()
        new_name = request.form['name'].strip()
        clash = _name_taken(new_name, exclude_id=s.id)
        if clash:
            flash(f'Another team member is already called {clash.name}. '
                  f'Two the same share one pay history — add a surname or an '
                  f'initial to tell them apart.', 'error')
            return render_template('admin/staff_form.html', staff=s)
        # Move her completed work with her, but only while the old name pointed
        # at exactly one person; otherwise it is not hers alone to take.
        moved = 0
        if old_name and new_name.lower() != old_name.lower() and not _name_taken(
                old_name, exclude_id=s.id):
            moved = _rename_assigned_jobs(old_name, new_name)
        s.name = new_name
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
        if moved:
            flash(f'Team member updated — and {moved} job{"" if moved == 1 else "s"} '
                  f'assigned to “{old_name}” now {"reads" if moved == 1 else "read"} '
                  f'“{new_name}”, so {new_name.split()[0]} keeps the pay already earned.',
                  'success')
        else:
            flash('Team member updated!', 'success')
        return redirect(url_for('contractors.team'))
    return render_template('admin/staff_form.html', staff=s)


@staff_bp.route('/<int:staff_id>/toggle', methods=['POST'])
@owner_required
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
@owner_required
def delete(staff_id):
    s = Staff.query.get_or_404(staff_id)
    db.session.delete(s)
    db.session.commit()
    flash('Team member removed.', 'success')
    return redirect(url_for('staff.index'))
