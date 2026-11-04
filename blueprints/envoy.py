"""The Envoy page: today's businesses, the drafts, the follow-ups, the score.

Owner-only (rbac.OWNER_ONLY_ENDPOINTS as well as owner_required): it holds the
settings that decide what is searched every morning and how much AI is spent.

A company Envoy has not been released to gets a 404 here, not a padlock. The
padlock rule (entitlements.py) is for features a company could buy; this one
is being released by hand to one company at a time, and showing it to the rest
would be advertising something they cannot have. A released company that is
not on the plan gets the ordinary upgrade page.

Nothing on this page sends anything to a prospect. A draft is copied, or taken
to the lead's own page, where the existing send (prospecting.send_outreach)
and its rules apply.
"""
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from auth import owner_required
from extensions import db

envoy_bp = Blueprint('envoy', __name__, url_prefix='/envoy')


def released(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        import envoy
        if not envoy.admitted():
            abort(404)
        if not envoy.entitled():
            import entitlements
            entitlements.record_denial('envoy', path=request.path)
            return redirect(url_for('billing.upgrade', feature='envoy'))
        return f(*args, **kwargs)
    return decorated


@envoy_bp.route('/')
@owner_required
@released
def page():
    import envoy
    from models import Prospect
    return render_template('admin/envoy.html', data=envoy.page(),
                           categories=sorted(Prospect.CATEGORY_LABELS.items(),
                                             key=lambda kv: kv[1]))


@envoy_bp.route('/settings', methods=['POST'])
@owner_required
@released
def save():
    import envoy
    for note in envoy.save_settings(request.form):
        flash(note, 'info')
    db.session.commit()
    flash('Envoy settings saved.', 'success')
    return redirect(url_for('envoy.page'))


@envoy_bp.route('/run', methods=['POST'])
@owner_required
@released
def run_now():
    """Do this morning's run now rather than waiting for the timetable. Still
    once a day: a second press drafts anything missing and finds nothing new."""
    import envoy
    if not envoy.is_on():
        flash(envoy.why_off() or 'Envoy is off.', 'error')
        return redirect(url_for('envoy.page'))
    out = envoy.run_daily(force=True)
    found = out.get('found', 0)
    flash((out.get('detail') or f'{found} new businesses found.').capitalize()
          + ('' if found or not out.get('drafted') else
             f' Drafted {out["drafted"]} waiting from before.'), 'success')
    return redirect(url_for('envoy.page'))


@envoy_bp.route('/<int:prospect_id>/redraft', methods=['POST'])
@owner_required
@released
def redraft(prospect_id):
    import envoy
    from models import Prospect
    p = Prospect.query.get_or_404(prospect_id)
    if p.source != envoy.SOURCE:
        abort(404)
    ai = envoy.write_drafts(p)
    flash(f'Redrafted {p.business_name}.' + ('' if ai else
          ' Written from the plain template (AI is off, or today\'s AI limit is used).'),
          'success')
    return redirect(url_for('envoy.page') + f'#p{p.id}')
