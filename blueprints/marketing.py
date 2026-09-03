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
from flask import (Blueprint, render_template, redirect, url_for, abort,
                   request, make_response)

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
        if request.method != 'GET':
            return None
        if not product.is_product_site():
            return None                 # a real CRM lives here; leave it alone

        # `/login` on the product domain used to render the single-business
        # CRM sign-in: a form titled "Your Cleaning Company" saying no owner
        # login exists, on a host where that is true and always will be. It is
        # linked from the main navigation, so it was the second thing a
        # prospect clicked. There is no CRM at akyehq.com -- every business is
        # on its own address -- so the honest answer is to ask which one.
        if request.path == '/login':
            return redirect(url_for('marketing.workspace'))

        if request.path != '/':
            return None
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


@marketing_bp.route('/terms')
def terms():
    _require_product_site()
    return render_template('marketing/legal_terms.html', **_legal_ctx())


@marketing_bp.route('/privacy')
def privacy():
    _require_product_site()
    return render_template('marketing/legal_privacy.html', **_legal_ctx())


@marketing_bp.route('/subprocessors')
def subprocessors():
    _require_product_site()
    return render_template('marketing/legal_subprocessors.html', **_legal_ctx())


def _legal_ctx():
    """One date for all three, so they cannot silently disagree about when they
    were last changed."""
    import os
    from blueprints.signup import signups_open
    return {'UPDATED': os.environ.get('LEGAL_UPDATED', '29 August 2026'),
            'signups_open': signups_open()}


@marketing_bp.route('/pricing')
def pricing():
    _require_product_site()
    from blueprints.signup import signups_open
    return render_template('marketing/pricing.html',
                           plans=entitlements.PLANS,
                           signups_open=signups_open())


@marketing_bp.route('/workspace', methods=['GET', 'POST'])
def workspace():
    """Send somebody to their own company's sign-in page.

    Deliberately looks nothing up. Typing an address here and being told
    "no such company" would let anybody enumerate our customer list one guess
    at a time, and the list of which cleaning companies pay for which software
    is exactly what a competitor would like. So this normalises what was typed
    and redirects. A company that does not exist gets that host's own error,
    which tells the visitor nothing they did not already type.
    """
    _require_product_site()
    import re
    error = None
    typed = ''
    if request.method == 'POST':
        typed = (request.form.get('workspace') or '').strip().lower()
        # Accept anything they might paste: a bare name, the full host, a URL.
        typed = re.sub(r'^https?://', '', typed).split('/')[0]
        base = (product.domain() or '').lower()
        if base and typed.endswith('.' + base):
            typed = typed[:-(len(base) + 1)]
        slug = re.sub(r'[^a-z0-9-]', '', typed)
        if not slug:
            error = 'Please enter your company\'s address.'
        elif not base:
            error = 'This deployment has no company addresses configured.'
        else:
            scheme = product.scheme_for(base)
            return redirect(f'{scheme}://{slug}.{base}/login')
    from blueprints.signup import signups_open
    return render_template('marketing/workspace.html', error=error, typed=typed,
                           signups_open=signups_open())


@marketing_bp.route('/robots.txt')
def robots():
    """What a crawler may look at.

    Only exists on the product's own domain. A cleaning company's CRM is not
    something we want indexed -- every tenant host returns 404 here, and the
    tenant pages a customer legitimately shares (a booking page, a quote) carry
    their own rules.
    """
    _require_product_site()
    base = _base()
    body = '\n'.join([
        'User-agent: *',
        'Allow: /',
        # Nothing behind a login, and nothing that is a single-use link.
        'Disallow: /login',
        'Disallow: /workspace',
        'Disallow: /api/',
        '',
        f'Sitemap: {base}/sitemap.xml',
        '',
    ])
    resp = make_response(body)
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return resp


@marketing_bp.route('/sitemap.xml')
def sitemap():
    """The pages worth indexing, which is only the public ones."""
    _require_product_site()
    base = _base()
    pages = [
        ('/', '1.0'),
        (url_for('marketing.pricing'), '0.9'),
        (url_for('marketing.terms'), '0.3'),
        (url_for('marketing.privacy'), '0.3'),
        (url_for('marketing.subprocessors'), '0.2'),
    ]
    urls = '\n'.join(
        f'  <url><loc>{base}{path}</loc><priority>{pri}</priority></url>'
        for path, pri in pages)
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f'{urls}\n</urlset>\n')
    resp = make_response(body)
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return resp


def _base():
    """The address to advertise, without a trailing slash.

    A sitemap is a promise that these URLs exist. This read crm_base(), which
    prefers CRM_BASE — pointed at the bare apex — so the sitemap handed search
    engines /pricing, /terms, /privacy and /subprocessors on a host that answers
    404 to all four. See product.canonical_base()."""
    import product
    return product.canonical_base().rstrip('/')


@marketing_bp.route('/early-access', methods=['GET', 'POST'])
def early_access():
    """For somebody who wants it before the door is open.

    Signups stay shut while the first ten companies are onboarded by hand, and
    that window is weeks long. Without this, every visitor who arrives in it —
    from a search, from a Facebook group, from a link somebody forwarded — has
    no way to raise their hand except spotting an email address in the footer.

    The details are written down AND emailed. The write can fail; the person
    filling in the form cannot be the one who pays for that.
    """
    _require_product_site()
    from blueprints.signup import signups_open

    # Door open? Then this page has no reason to exist — send them to sign up.
    if signups_open():
        return redirect(url_for('signup.signup'))

    errors = {}
    form = {k: (request.form.get(k) or '').strip()
            for k in ('name', 'company', 'email', 'phone', 'cleaners', 'note')}

    if request.method == 'POST':
        if not form['name']:
            errors['name'] = 'Please tell us your name.'
        if not form['email'] or '@' not in form['email']:
            errors['email'] = 'We need an email to reply to.'

        if not errors:
            import provisioning, control_plane, product
            saved = False
            try:
                saved = control_plane.add_lead(
                    provisioning._engine(),
                    source=(request.referrer or '')[:120] or 'direct', **form)
            except Exception:
                saved = False

            # Emailed as well as written down, so a failed write still reaches
            # a person. This is somebody asking to give us money.
            try:
                import notifications
                to = product.support_email()
                if to:
                    body = '\n'.join(
                        f'{k.title()}: {v}' for k, v in form.items() if v)
                    notifications.send_email(
                        to, product.name(),
                        f'Early access request — {form["company"] or form["name"]}',
                        f'<pre>{body}</pre>'
                        f'<p>Stored: {"yes" if saved else "NO — write failed"}</p>')
            except Exception:
                pass

            return render_template('marketing/early_access.html',
                                   done=True, form=form, errors={})

    return render_template('marketing/early_access.html',
                           done=False, form=form, errors=errors)

