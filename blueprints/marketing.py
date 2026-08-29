"""The product's public front door.

Until now the root of the product domain redirected to a login form, which is a
page for people who already have an account. Nobody could find out what this is
or sign up for it.

## It only ever appears on the product's own domain

Three deployments share this code and only one of them should ever show these
pages:

    dazzleandshine…            no BASE_DOMAIN -> a business's own CRM. Never.
    acme.akye.com              a customer's CRM. Never.
    akye.com                   the product. Here.

Enforced by checking the host rather than by hoping the routes are never hit,
because `/` is the one URL somebody will always find.

## The pricing page reads the real plans

It renders from entitlements.PLANS, the same table the software enforces. A
pricing page maintained separately drifts, and the direction it drifts is
always the same: it promises something the product then refuses to do, and the
customer finds out after paying.
"""
from flask import Blueprint, render_template, redirect, url_for, abort

import entitlements
import product

marketing_bp = Blueprint('marketing', __name__)


def _require_product_site():
    if not product.is_product_site():
        abort(404)


def install(app):
    """Serve the landing page at `/` on the product domain only.

    A before_request rather than a route, because `/` already belongs to the
    dashboard and must keep belonging to it everywhere else. This intercepts
    exactly one path on exactly one host.
    """
    from flask import request

    @app.before_request
    def _front_door():
        if request.path != '/' or request.method != 'GET':
            return None
        if not product.is_product_site():
            return None                 # a real CRM lives here; leave it alone
        from flask import session
        if session.get('logged_in'):
            # Signed in on the product domain itself. There is no CRM here to
            # show them -- their business is on its own address.
            return redirect(url_for('marketing.home'))
        return home()


@marketing_bp.route('/home')
def home():
    _require_product_site()
    from blueprints.signup import signups_open
    return render_template('marketing/home.html',
                           plans=entitlements.PLANS,
                           signups_open=signups_open())


@marketing_bp.route('/pricing')
def pricing():
    _require_product_site()
    from blueprints.signup import signups_open
    return render_template('marketing/pricing.html',
                           plans=entitlements.PLANS,
                           signups_open=signups_open())
