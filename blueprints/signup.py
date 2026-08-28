"""A cleaning company giving itself an account, without anybody helping.

Someone types their business name, picks an address, and a minute later they are
looking at their own empty CRM at their own web address, signed in.

## Two hosts, two sessions, one bridge

Signup happens on the product's own domain — rollcall.com/signup. The account
that comes out of it lives at acme.rollcall.com. Those are different hosts, so a
session cookie set on one is not sent to the other, and that is deliberate: a
cookie scoped to the parent domain would be a session valid on *every* company's
subdomain, which is the opposite of the isolation the rest of this is built on.

So signup issues a single-use token, redirects to the company's own address, and
that page spends the token to create the session. The bridge is one token, good
once, for twenty-four hours.

## The order is chosen for what happens when it breaks

    validate  ->  create schema  ->  build tables  ->  owner account  ->  record company

The company is recorded last. A crash before that leaves an orphan schema, which
is untidy and invisible. Recording first would leave a company that exists and
resolves and has no tables — a customer meeting a stack trace in their first
minute. If anything fails the schema is dropped, so a retry with the same
address works rather than colliding with the wreckage of the first attempt.

## Off unless deliberately switched on

No BASE_DOMAIN means no subdomains, which means signup cannot work and does not
appear. The single-business instance running today has no BASE_DOMAIN, so these
routes are simply not there.
"""
import os
import re

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, jsonify, abort)

import control_plane
import provisioning
import tenancy
from extensions import db
from models import User, LoginToken

signup_bp = Blueprint('signup', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$', re.I)


def signups_open():
    """Signup needs a domain to carve subdomains out of, and an explicit yes.

    SIGNUPS_OPEN=0 keeps tenancy working while the door is shut -- which is the
    state to be in while onboarding the first few companies by hand."""
    return bool(os.environ.get('BASE_DOMAIN')) and \
        (os.environ.get('SIGNUPS_OPEN', '1') != '0')


def _require_open():
    if not signups_open():
        abort(404)


def suggest_slug(name):
    """A first guess at an address from a business name."""
    s = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')
    s = re.sub(r'-+', '-', s)[:40].strip('-')
    return s if tenancy.valid_slug(s) else ''


def _engine():
    return provisioning._engine()


@signup_bp.route('/signup/check')
def check_slug():
    """Is this address free? Called as somebody types."""
    _require_open()
    slug = (request.args.get('slug') or '').strip().lower()
    if not tenancy.valid_slug(slug):
        return jsonify({
            'ok': False,
            'reason': 'Use 3–40 lower-case letters, numbers or hyphens.'
                      if slug not in tenancy.RESERVED_SLUGS
                      else 'That address is reserved.'})
    engine = _engine()
    control_plane.ensure_table(engine)
    if control_plane.find(engine, slug):
        return jsonify({'ok': False, 'reason': 'Already taken.'})
    return jsonify({'ok': True, 'host': f'{slug}.{os.environ["BASE_DOMAIN"]}'})


@signup_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    _require_open()
    base = os.environ['BASE_DOMAIN']
    form = {}

    if request.method == 'POST':
        form = {k: (request.form.get(k) or '').strip()
                for k in ('business', 'slug', 'name', 'email')}
        form['email'] = form['email'].lower()
        password = request.form.get('password') or ''
        slug = form['slug'].lower() or suggest_slug(form['business'])

        error = _validate(form, slug, password)
        if error:
            return render_template('admin/signup.html', form=form, slug=slug,
                                   base=base, error=error)

        try:
            token = _create_everything(slug, form, password)
        except Exception as e:
            # Whatever went wrong, the half-built company is removed so the same
            # address can be tried again.
            _cleanup(slug)
            import errors
            errors.capture(e, path='/signup', method='POST')
            return render_template(
                'admin/signup.html', form=form, slug=slug, base=base,
                error='Something went wrong setting your account up. Nothing was '
                      'charged and nothing was kept — please try again, and if it '
                      'happens twice tell us.')

        # Over to their own address, where the session belongs.
        scheme = 'http' if base.startswith('localhost') else 'https'
        return redirect(f'{scheme}://{slug}.{base}/welcome/{token}')

    return render_template('admin/signup.html', form=form, slug='', base=base,
                           error=None)


def _validate(form, slug, password):
    if not form['business']:
        return 'What is the business called?'
    if not form['name']:
        return 'What is your name?'
    if not EMAIL_RE.match(form['email'] or ''):
        return 'That email address does not look right.'
    if len(password) < 8:
        return 'Please use a password of at least 8 characters.'
    if password.lower() in ('password', '12345678', 'changeme'):
        return 'That password is too easy to guess.'
    if not tenancy.valid_slug(slug):
        return ('Pick a web address of 3–40 lower-case letters, numbers or '
                'hyphens — and not a reserved word like "www" or "admin".')
    engine = _engine()
    control_plane.ensure_table(engine)
    if control_plane.find(engine, slug):
        return f'"{slug}" is already taken. Try another.'
    return None


def _create_everything(slug, form, password):
    """Schema, tables, seeds, owner account, control-plane record. Returns the
    one-time token that logs them in on their own address."""
    engine = _engine()
    schema = tenancy.schema_for(slug)

    provisioning.create_schema(engine, schema)
    provisioning.migrate_schema(engine, schema)

    from flask import current_app
    provisioning.seed(current_app, schema)

    with tenancy.use_tenant(schema):
        owner = User(name=form['name'], username=form['email'], role='owner',
                     active=True)
        owner.set_password(password)
        db.session.add(owner)
        db.session.commit()
        # Their business name, so the CRM is theirs from the first screen rather
        # than saying "Your Cleaning Company" at them.
        from models import BusinessSetting
        BusinessSetting.set('business_name', form['business'])
        BusinessSetting.set('email', form['email'])
        db.session.commit()
        raw, _ = LoginToken.issue(owner, 'signup', email=form['email'])

    control_plane.create(engine, slug, form['business'], form['email'])
    control_plane.mark_provisioned(engine, slug)
    return raw


def _cleanup(slug):
    """Remove a half-built company so the address can be reused."""
    try:
        engine = _engine()
        schema = tenancy.schema_for(slug)
        if provisioning.schema_exists(engine, schema):
            provisioning.drop_schema(engine, schema)
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text('DELETE FROM public.organizations WHERE slug = :s'),
                         {'s': slug})
    except Exception:
        pass


@signup_bp.route('/welcome/<token>')
def welcome(token):
    """Spend the signup token and start the session, on the company's own host.

    Lives here rather than on the signup domain because a session cookie is
    scoped to the host that sets it, and this is the host it needs to work on.
    """
    if not tenancy.is_tenant():
        # Reached on the product's own domain, where there is no company and no
        # account. Almost always somebody re-opening an old link.
        return redirect(url_for('signup.signup') if signups_open() else '/')

    user = LoginToken.consume(token, 'signup')
    if not user:
        return render_template('admin/welcome_expired.html')

    session.clear()
    session.permanent = True
    session['logged_in'] = True
    session['role'] = user.role
    session['user_id'] = user.id
    session['user_name'] = user.name
    return redirect(url_for('settings.getting_started'))
