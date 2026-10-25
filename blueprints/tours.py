"""Serves one step-by-step guide to the page's tour script (static/tour.js).

Behind the login like every other admin page: the guides say nothing secret,
but they describe the admin screens, and there is no reason to publish them.
"""
from flask import Blueprint, abort, jsonify

import howto
from auth import login_required

tours_bp = Blueprint('tours', __name__, url_prefix='/help/tour')


@tours_bp.route('/<key>.json')
@login_required
def guide(key):
    g = howto.by_key(key)
    if g is None:
        abort(404)
    return jsonify(howto.public(g))
