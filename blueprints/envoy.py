"""The Envoy page: today's businesses, the drafts, the follow-ups, the score.

Owner-only (rbac.OWNER_ONLY_ENDPOINTS as well as owner_required): it holds the
settings that decide what is searched every morning and how much AI is spent.

A company Envoy has not been released to gets a 404 here, not a padlock. The
padlock rule (entitlements.py) is for features a company could buy; this one
is being released by hand to one company at a time, and showing it to the rest
would be advertising something they cannot have. A released company that is
not on the plan gets the ordinary upgrade page.

Nothing is sent to a prospect unless the owner presses Send on a draft, and
then through prospecting.send_outreach, the same send the call list uses
(envoy.send adds the legal footer and its own checks).
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
    out = envoy.run_daily(force=True, seconds=envoy.PAGE_DRAFT_SECONDS)
    found = out.get('found', 0)
    flash((out.get('detail') or f'{found} new businesses found.').capitalize()
          + ('' if found or not out.get('drafted') else
             f' Drafted {out["drafted"]} waiting from before.')
          + (f' {out["waiting"]} more are being drafted; refresh in a minute.'
             if out.get('waiting') else ''), 'success')
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
    envoy.read_site(p, refresh=True)
    db.session.commit()
    ai = envoy.write_drafts(p)
    flash(f'Redrafted {p.business_name}.' + ('' if ai else
          ' Written from the plain template (AI is off, or today\'s AI limit is used).'),
          'success')
    return redirect(url_for('envoy.page') + f'#p{p.id}')


@envoy_bp.route('/<int:prospect_id>/send', methods=['POST'])
@owner_required
@released
def send(prospect_id):
    """Send one draft, as the owner edited it, to the address shown."""
    import envoy
    from flask import session
    from models import Prospect
    p = Prospect.query.get_or_404(prospect_id)
    if not envoy.drafts_for([p.id]).get(p.id):
        abort(404)
    ok, said = envoy.send(p, request.form.get('kind'), request.form.get('to'),
                          request.form.get('subject'), request.form.get('body'),
                          sent_by=session.get('user_name'))
    flash(said, 'success' if ok else 'error')
    return redirect(url_for('envoy.page') + f'#p{p.id}')
