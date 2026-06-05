import os
from functools import wraps
from flask import session, redirect, url_for


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated


def check_credentials(username, password):
    return (
        username == os.environ.get('ADMIN_USER', 'admin') and
        password == os.environ.get('ADMIN_PASS', 'changeme')
    )
