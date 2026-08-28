"""Team Logins — owner-only management of who can sign into the CRM.
Create a login for a VA or future hire, set their role (Owner sees money,
Team does not), reset passwords, disable, or remove."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from entitlements import requires_plan
from auth import owner_required
from extensions import db
from models import User

team_logins_bp = Blueprint('team_logins', __name__, url_prefix='/logins')


@team_logins_bp.route('/')
@owner_required
@requires_plan('team_logins')
def index():
    users = User.query.order_by(User.active.desc(), User.name).all()
    return render_template('admin/team_logins.html', users=users)


@team_logins_bp.route('/add', methods=['POST'])
@owner_required
def add():
    name = (request.form.get('name') or '').strip()
    username = (request.form.get('username') or '').strip().lower()
    password = request.form.get('password') or ''
    role = request.form.get('role', 'team')
    if role not in ('owner', 'team'):
        role = 'team'
    if not name or not username or not password:
        flash('Please fill in name, username, and password.', 'error')
        return redirect(url_for('team_logins.index'))
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'error')
        return redirect(url_for('team_logins.index'))
    if User.query.filter_by(username=username).first():
        flash(f'The username "{username}" is already taken.', 'error')
        return redirect(url_for('team_logins.index'))
    u = User(name=name, username=username, role=role, active=True)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    flash(f'Login created for {name}. ✅', 'success')
    return redirect(url_for('team_logins.index'))


@team_logins_bp.route('/<int:user_id>/toggle', methods=['POST'])
@owner_required
def toggle(user_id):
    u = User.query.get_or_404(user_id)
    u.active = not u.active
    db.session.commit()
    flash(f'{u.name} is now {"active" if u.active else "disabled"}.', 'success')
    return redirect(url_for('team_logins.index'))


@team_logins_bp.route('/<int:user_id>/reset', methods=['POST'])
@owner_required
def reset(user_id):
    u = User.query.get_or_404(user_id)
    password = request.form.get('password') or ''
    if len(password) < 6:
        flash('New password must be at least 6 characters.', 'error')
        return redirect(url_for('team_logins.index'))
    u.set_password(password)
    db.session.commit()
    flash(f'Password reset for {u.name}. ✅', 'success')
    return redirect(url_for('team_logins.index'))


@team_logins_bp.route('/<int:user_id>/delete', methods=['POST'])
@owner_required
def delete(user_id):
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash('Login removed.', 'success')
    return redirect(url_for('team_logins.index'))
