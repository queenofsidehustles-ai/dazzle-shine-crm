"""The Envoy page, and the hourly call that does the morning's work.

Everything Envoy decides lives in envoy.py; this is the routes. The page is the
owner's alone: it holds the day's drafts, a plan-feature spend (a lead search
every morning) and the settings that start it all, so every route here is
owner-only, plan-gated, and does not exist at all for a company Envoy has not
been released to -- a 404, not an upsell, because there is nothing for that
company to buy yet.
"""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

import envoy
from auth import owner_required
from entitlements import requires_plan

envoy_bp = Blueprint('envoy', __name__)


def released_only(f):
    """404 for a company Envoy has not been released to. Checked before the
    plan, so such a company is never sent to an upgrade page for it."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not envoy.released():
            abort(404)
        return f(*args, **kwargs)
    return decorated


@envoy_bp.route('/envoy/')
@owner_required
@released_only
@requires_plan(envoy.FEATURE)
def page():
    import places_finder
    from models import Prospect
    day = envoy.today()
    cfg = envoy.settings()
    made = envoy.todays_prospects(day)
    run = envoy.todays_run(day)
    return render_template(
        'admin/envoy.html',
        st=envoy.state(),
        cfg=cfg,
        day=day,
        category=envoy.category_for(day, cfg),
        audience=envoy.AUDIENCE,
        run=run,
        made=made,
        drafts=envoy.drafts_for(made),
        site_emails=envoy.site_emails,
        followups=envoy.followups(day),
        score=envoy.scoreboard(day),
        ai_used=envoy.ai_used(day),
        categories=list(places_finder.CATEGORY_QUERIES),
        category_labels=Prospect.CATEGORY_LABELS,
        weekdays=envoy.WEEKDAYS,
        run_after=envoy.RUN_AFTER_HOUR,
    )


@envoy_bp.route('/envoy/settings', methods=['POST'])
@owner_required
@released_only
@requires_plan(envoy.FEATURE)
def save_settings():
    problems = envoy.save_settings(request.form)
    if problems:
        for p in problems:
            flash(p, 'error')
    else:
        flash('Envoy settings saved.' + (' Envoy is on.' if envoy.setting('envoy_enabled') == '1'
                                         else ' Envoy is off.'), 'success')
    return redirect(url_for('envoy.page'))


@envoy_bp.route('/envoy/run', methods=['POST'])
@owner_required
@released_only
@requires_plan(envoy.FEATURE)
def run_now():
    """Do this morning's work now, rather than wait for the next hourly call.
    Still once a day: if this morning's search has happened it is not redone."""
    out = envoy.run(force=True)
    if out.get('skipped'):
        flash(out['skipped'], 'error')
    else:
        bits = [f"{out['created']} new business{'es' if out['created'] != 1 else ''} added"]
        if out['drafted']:
            bits.append(f"{out['drafted']} drafted")
        if out['waiting']:
            bits.append(f"{out['waiting']} still to draft (press again)")
        flash('. '.join(bits) + '.', 'success')
    return redirect(url_for('envoy.page'))


@envoy_bp.route('/envoy/draft/<int:prospect_id>', methods=['POST'])
@owner_required
@released_only
@requires_plan(envoy.FEATURE)
def redraft(prospect_id):
    """Write (or rewrite) one prospect's drafts. Envoy's own prospects only:
    the others were not found from a listing Envoy read."""
    from models import Prospect
    p = Prospect.query.get_or_404(prospect_id)
    if p.source != 'envoy':
        abort(404)
    st = envoy.state()
    if not st['ready']:
        flash(st['reason'], 'error')
        return redirect(url_for('envoy.page'))
    row = envoy.write_draft(p)
    flash(f'Drafts written for {p.business_name}'
          + (' (from the template, not AI).' if row.source != 'ai' else '.'), 'success')
    return redirect(url_for('envoy.page') + f'#p{p.id}')


@envoy_bp.route('/api/envoy-daily', methods=['POST'])
def cron():
    """Woken hourly by scheduler.py, at this company's own address.

    Counts only in the reply: it lands in a CI log."""
    from blueprints.api import _cron_key_ok
    if not _cron_key_ok():
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 403
    if not envoy.released():
        return jsonify({'ok': True, 'skipped': 'not released to this company'}), 200
    try:
        import demo_guard
        if demo_guard.active():
            return jsonify({'ok': True, 'skipped': 'demo company'}), 200
    except Exception:
        pass
    try:
        return jsonify(envoy.run())
    except Exception as e:
        from extensions import db
        db.session.rollback()
        try:
            import errors
            errors.capture(e, path='/api/envoy-daily', method='POST')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}'}), 200
