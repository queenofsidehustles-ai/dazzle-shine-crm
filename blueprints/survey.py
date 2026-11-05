"""The "what got in the way" survey, answered from the emailed link.

    GET  /survey/<token>    the form, with the tapped answer already ticked
    POST /survey/<token>    save it

No sign-in: the people this is for are the ones who stopped coming back. The
link carries which company and which group, signed with SECRET_KEY, and it
only works on that company's own address, so one company's link cannot
answer for another.

A GET never records anything. Mail scanners follow every link in a message,
and a survey that counted those clicks would report a bottleneck nobody has.
Tapping an option in the email opens the page with it ticked; the person
presses the button.

See survey.py for who is asked and why.
"""
from flask import Blueprint, abort, g, render_template, request

import control_plane
import provisioning
import survey
import tenancy

survey_bp = Blueprint('survey', __name__)


def _engine():
    return provisioning._engine()


def _org_for(raw):
    """(org, segment) for a link that belongs to this address, else (org, None).

    A bad, old or foreign link is not a 404: somebody who finds the page a
    month late should be told it is out of date, not that it never existed.
    """
    slug = getattr(g, 'tenant_slug', None)
    if not slug or not tenancy.is_tenant():
        abort(404)
    org = control_plane.find(_engine(), slug)
    if not org:
        abort(404)
    link_slug, seg = survey.read_token(raw)
    if link_slug != org['slug'] or not seg:
        return org, None
    return org, seg


@survey_bp.route('/survey/<token>', methods=['GET', 'POST'])
def answer(token):
    org, seg = _org_for(token)
    if not seg:
        return render_template('public/survey.html', state='bad', org=org), 400

    if request.method == 'POST':
        cleaned = survey.clean(request.form)
        if survey.is_empty(cleaned):
            return render_template(
                'public/survey.html', state='ask', org=org, seg=seg,
                ticked=[], answer=cleaned, error=True,
                options=survey.BLOCKERS, stuck=survey.STUCK,
                follow_up=survey.FOLLOW_UP, max_blockers=survey.MAX_BLOCKERS), 400
        survey.save(_engine(), org, seg, cleaned)
        return render_template('public/survey.html', state='done', org=org,
                               wants_call=cleaned['wants_call'])

    earlier = survey.existing(_engine(), org['slug']) or {}
    ticked = [k for k in (earlier.get('blockers') or '').split(',') if k]
    tapped = request.args.get('a')
    if tapped in survey.BLOCKER_LABELS and tapped not in ticked:
        ticked = ([tapped] + ticked)[:survey.MAX_BLOCKERS]
    return render_template(
        'public/survey.html', state='ask', org=org, seg=seg, ticked=ticked,
        answer=earlier, error=False, options=survey.BLOCKERS,
        stuck=survey.STUCK, follow_up=survey.FOLLOW_UP,
        max_blockers=survey.MAX_BLOCKERS)
