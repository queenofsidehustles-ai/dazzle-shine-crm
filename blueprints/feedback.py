"""Beta feedback, from wherever they happen to be standing.

A beta tester who has to leave what they are doing, find an email address and
describe where they were will mostly not bother -- and the ones who do send
"it broke" without saying which page. So this is on every screen, takes a
screenshot and a voice note, and captures the page, the release and the
browser itself rather than asking.

It writes to the control plane, not to the company's own database. Feedback
filed inside each tenant would mean logging into every company to find out
what the beta said, which is how feedback stops being read.
"""
import base64
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request, session

import control_plane
import product
import provisioning
from auth import login_required

feedback_bp = Blueprint('feedback', __name__)

# A screenshot is downscaled in the browser before it is sent. This is the
# backstop: past it the note is kept and the picture is dropped, because a
# note that arrives beats a note refused for being too big.
MAX_SHOT_BYTES = 3 * 1024 * 1024

KINDS = ('issue', 'idea', 'confusing', 'praise')


def _engine():
    return provisioning._engine()


@feedback_bp.route('/feedback', methods=['POST'])
@login_required
def send():
    """Take one piece of feedback from any page."""
    data = request.get_json(silent=True) or {}
    body = (data.get('body') or '').strip()
    if not body:
        return jsonify({'ok': False, 'say': 'Tell me what happened first.'}), 400

    kind = (data.get('kind') or 'issue').strip()
    if kind not in KINDS:
        kind = 'issue'

    shot, shot_type = None, None
    raw = data.get('shot') or ''
    if raw.startswith('data:image/'):
        try:
            header, b64 = raw.split(',', 1)
            shot = base64.b64decode(b64)
            shot_type = header.split(':', 1)[1].split(';', 1)[0]
            if len(shot) > MAX_SHOT_BYTES:
                # Keep the words, lose the picture. Refusing the whole thing
                # over a large screenshot loses the part that matters.
                shot, shot_type = None, None
        except Exception:
            shot, shot_type = None, None

    engine = _engine()
    try:
        control_plane.ensure_table(engine)
        fid = control_plane.add_feedback(
            engine,
            org_slug=_slug(),
            user_name=session.get('user_name'),
            user_role=session.get('role'),
            kind=kind,
            body=body[:4000],
            # Captured, not asked for. "It broke" from somebody who cannot
            # remember the page is the most common thing a beta tester sends.
            page=(data.get('page') or '')[:300],
            endpoint=(data.get('endpoint') or '')[:120],
            release=_release(),
            user_agent=(request.headers.get('User-Agent') or '')[:300],
            viewport=(data.get('viewport') or '')[:20],
            shot=shot, shot_type=shot_type,
        )
    except Exception:
        try:
            import errors
            errors.capture(RuntimeError('feedback could not be saved'),
                           path='/feedback', method='POST')
        except Exception:
            pass
        return jsonify({'ok': False,
                        'say': 'That did not save. Try once more.'}), 500

    _tell_us(kind, body, fid, shot is not None)
    return jsonify({'ok': True, 'say': 'Sent. Thank you — that helps.'})


def _slug():
    """Which company this came from. Set per request in app.py."""
    try:
        from flask import g
        return getattr(g, 'tenant_slug', None)
    except Exception:
        return None


def _release():
    try:
        import branding
        return branding.version()
    except Exception:
        return None


def _tell_us(kind, body, fid, has_shot):
    """Email it over. Beta feedback nobody reads for a week is not feedback."""
    to = product.support_email()
    if not to:
        return
    try:
        from notifications import send_email
        from html import escape
        where = f'{_slug() or "unknown"} · {_release() or "unknown release"}'
        send_email(
            to, product.name(), f'[{kind}] beta feedback from {_slug() or "a tester"}',
            f'<p style="font-size:15px;white-space:pre-wrap">{escape(body)}</p>'
            f'<p style="color:#777;font-size:13px">{escape(where)}'
            f'{" · screenshot attached in the console" if has_shot else ""}</p>',
            from_name=product.name(),
            from_email=product.from_email() or to,
            reply_to=to,
            # Our key. A tester's feedback must not be billed to the company
            # they are testing, or fail because they never connected Resend.
            api_key=product.resend_api_key() or None)
    except Exception:
        pass


@feedback_bp.route('/feedback/<int:feedback_id>/shot')
@login_required
def shot(feedback_id):
    """The screenshot for one piece of feedback."""
    if session.get('role') != 'owner':
        return ('', 404)
    blob, ctype = control_plane.feedback_shot(_engine(), feedback_id)
    if not blob:
        return ('', 404)
    return Response(blob, mimetype=ctype,
                    headers={'Cache-Control': 'private, max-age=600'})
