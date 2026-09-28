"""Team Logins — owner-only management of tenant CRM accounts."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from entitlements import requires_plan
from auth import owner_required
from extensions import db
from models import User
import rbac

team_logins_bp = Blueprint('team_logins', __name__, url_prefix='/logins')


@team_logins_bp.route('/')
@owner_required
@requires_plan('team_logins')
def index():
    users = User.query.order_by(User.active.desc(), User.name).all()
    return render_template(
        'admin/team_logins.html',
        users=users,
        role_options=rbac.ROLE_OPTIONS,
        role_label=rbac.role_label,
    )


@team_logins_bp.route('/add', methods=['POST'])
@owner_required
def add():
    """Create a login and invite its owner to choose her own password.

    Used to take a password typed here, by the owner, on somebody else's
    behalf -- one more person who briefly knew it, and one more thing to
    hand over safely. This sends an invite link instead, the same one-path
    -in team_logins.reset already switched to; the username a login signs in
    with is the same address the invite goes to, so there's one field to
    fill in here, not two."""
    from notifications import looks_like_email
    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    role = rbac.canonical_role(request.form.get('role'))
    if not role:
        flash('Choose a valid account role.', 'error')
        return redirect(url_for('team_logins.index'))
    if not name or not email:
        flash('Please fill in name and email address.', 'error')
        return redirect(url_for('team_logins.index'))
    if not looks_like_email(email):
        flash('That does not look like an email address.', 'error')
        return redirect(url_for('team_logins.index'))
    if User.query.filter_by(username=email).first():
        flash(f'"{email}" already has a login.', 'error')
        return redirect(url_for('team_logins.index'))

    import secrets
    u = User(name=name, username=email, role=role, active=True)
    # Nobody is ever told this -- it exists only because the column can't be
    # empty. She sets the password that actually works on the invite link
    # below, same as everyone else's now does.
    u.set_password(secrets.token_urlsafe(24))
    db.session.add(u)
    db.session.commit()

    # Index this login so a "which company do I sign into" lookup by email
    # (root-domain /login) can find it. Best-effort: this account already
    # exists and works either way, even if the index write fails.
    import auth, control_plane, provisioning
    slug = auth.current_tenant_slug()
    if slug:
        control_plane.record_tenant_login(provisioning._engine(), email, slug)

    from blueprints.account import _invite_url, _send_invite
    from models import LoginToken
    raw, _tok = LoginToken.issue(u, 'invite', email=email)
    _send_invite(u, _invite_url(raw))

    flash(f'Invited {name} as {rbac.role_label(role)} — she chooses her own '
          f'password when she opens the link. ✅', 'success')
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
    """Send the same reset link /forgot sends, rather than the owner typing a
    new password on someone else's behalf.

    That used to mean a second person always knew a teammate's password, at
    least for the moment it was handed over -- by text, by sticky note,
    however. This is the one path a password ever gets set through now,
    self-service or owner-triggered, so there is only the one to secure."""
    u = User.query.get_or_404(user_id)
    if not u.active:
        flash(f"{u.name}'s login is disabled — enable it first so the link works.", 'error')
        return redirect(url_for('team_logins.index'))

    from blueprints.account import _reset_url, _send_reset, _recently_sent
    from models import LoginToken
    if _recently_sent(u):
        flash(f'A reset link already went to {u.name} in the last few minutes.', 'info')
        return redirect(url_for('team_logins.index'))
    raw, _tok = LoginToken.issue(u, 'reset', email=u.username)
    _send_reset(u, _reset_url(raw))
    flash(f'Reset link sent to {u.name}. ✅', 'success')
    return redirect(url_for('team_logins.index'))


@team_logins_bp.route('/<int:user_id>/delete', methods=['POST'])
@owner_required
def delete(user_id):
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash('Login removed.', 'success')
    return redirect(url_for('team_logins.index'))
