"""The few writes help tips make: a tip read, a suggestion turned down, a
suggestion followed. Each only touches the signed-in person's own record
(adoption.py), which is why every role may reach them (rbac)."""
from flask import Blueprint, abort, redirect, request, url_for

from auth import login_required
import adoption
import help_tips

tips_bp = Blueprint('tips', __name__, url_prefix='/tips')


def _key():
    key = (request.form.get('key') or (request.get_json(silent=True) or {}).get('key') or '').strip()
    return key if key in help_tips.TIPS else None


@tips_bp.route('/opened', methods=['POST'])
@login_required
def opened():
    key = _key()
    if key:
        source = (request.get_json(silent=True) or {}).get('source') or request.form.get('source')
        adoption.record_open(key, source='menu' if source == 'menu' else None)
    return ('', 204)


@tips_bp.route('/dismiss', methods=['POST'])
@login_required
def dismiss():
    """"Not now" on the Did you know? -- never suggested again."""
    key = _key()
    if key:
        adoption.dismiss(key)
    if request.accept_mimetypes.best == 'application/json' or request.is_json:
        return ('', 204)
    import security
    return redirect(security.local_target(request.form.get('next')) or url_for('admin.dashboard'))


@tips_bp.route('/go/<key>')
@login_required
def go(key):
    """"Show me" on the Did you know?: counted, then on to the feature."""
    if key not in help_tips.TIPS:
        abort(404)
    adoption.clicked(key)
    try:
        return redirect(url_for(key))
    except Exception:
        abort(404)
