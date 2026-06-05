from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import Staff
from extensions import db

staff_bp = Blueprint('staff', __name__, url_prefix='/staff')


@staff_bp.route('/')
@login_required
def index():
    staff = Staff.query.order_by(Staff.is_active.desc(), Staff.name).all()
    return render_template('admin/staff.html', staff=staff)


@staff_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        s = Staff(
            name=request.form['name'].strip(),
            phone=request.form.get('phone', '').strip(),
            email=request.form.get('email', '').strip(),
            color=request.form.get('color', '#7c3aed'),
            is_active='is_active' in request.form,
        )
        db.session.add(s)
        db.session.commit()
        flash('Team member added!', 'success')
        return redirect(url_for('staff.index'))
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
        db.session.commit()
        flash('Team member updated!', 'success')
        return redirect(url_for('staff.index'))
    return render_template('admin/staff_form.html', staff=s)


@staff_bp.route('/<int:staff_id>/delete', methods=['POST'])
@login_required
def delete(staff_id):
    s = Staff.query.get_or_404(staff_id)
    db.session.delete(s)
    db.session.commit()
    flash('Team member removed.', 'success')
    return redirect(url_for('staff.index'))
