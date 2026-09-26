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
minute. Provisioning owns its cleanup while it holds the slug lock, so a failed
request can never delete a tenant created by a competing request for the same
address.

## Open by default

Self-service is the product: a new client signs on and onboards themselves with
no one on the other end. BASE_DOMAIN is a hard requirement -- there is no
subdomain to carve a company out of without one, so no BASE_DOMAIN means signup
cannot work and does not appear. SIGNUPS_OPEN is the deliberate *off* switch for
a by-hand onboarding window (set it to 0 to close the door); leaving it unset
keeps signup open rather than closed.
"""
import os
import re
from contextlib import contextmanager

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, jsonify, abort)
from sqlalchemy import text

import control_plane
import provisioning
import tenancy
from auth import bind_authenticated_session
from extensions import db
from models import User, LoginToken

signup_bp = Blueprint('signup', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$', re.I)


class SlugTaken(Exception):
    """Raised when another signup wins the requested tenant address."""


def signups_open():
    """Signup needs a domain to carve subdomains out of. Otherwise: open.

    Self-service onboarding is the default. SIGNUPS_OPEN=0 is the deliberate
    off switch, for the rare stretch where companies are being onboarded by
    hand instead; anything else, including unset, leaves the door open.
    """
    return bool((os.environ.get('BASE_DOMAIN') or '').strip()) and \
        os.environ.get('SIGNUPS_OPEN') != '0'


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


@contextmanager
def _slug_lock(engine, slug):
    """Serialize provisioning for one tenant address across all app workers.

    A process-local lock is insufficient in production because separate workers
    can receive the same signup concurrently. PostgreSQL advisory locks are held
    by the dedicated connection for the whole provisioning attempt, including
    migrations and cleanup performed through other connections.
    """
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('Tenant signup requires PostgreSQL.')
    key = f'akye:tenant-provision:{slug}'
    with engine.connect() as conn:
        conn.execute(text('SELECT pg_advisory_lock(hashtext(:key))'), {'key': key})
        try:
            yield
        finally:
            conn.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': key})


def _ensure_control_plane(engine):
    """Create/repair public control-plane tables without first-boot DDL races.

    SQLAlchemy's create_all(checkfirst=True) is not atomic across workers: two
    requests can both observe a missing table and then collide creating the
    same PostgreSQL relation/type. Serialize only this initialization step with
    one database-wide advisory lock. Established deployments pay essentially
    nothing because ensure_table becomes a quick check while the lock is held.
    """
    if engine.dialect.name != 'postgresql':
        control_plane.ensure_table(engine)
        return
    key = 'akye:control-plane-init'
    with engine.connect() as conn:
        conn.execute(text('SELECT pg_advisory_lock(hashtext(:key))'), {'key': key})
        try:
            control_plane.ensure_table(engine)
        finally:
            conn.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': key})


def _seed_strict(app, schema):
    """Apply every required starter seed and fail the signup if any seed fails.

    The boot-time seed helper is deliberately tolerant so one optional repair
    cannot take an established deployment down. New-company provisioning has a
    different contract: a tenant must never be declared ready when its required
    starter template only partly exists.
    """
    with app.app_context():
        with tenancy.use_tenant(schema):
            import app as app_module
            for fn in ('_seed_checklists', '_seed_scripts', '_seed_sales_scripts',
                       '_seed_sops', '_seed_email_templates', '_seed_pricing_defaults',
                       '_seed_message_templates'):
                getattr(app_module, fn)()


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
    _ensure_control_plane(engine)
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

        try:
            error = _validate(form, slug, password)
        except Exception as e:
            import errors
            try:
                errors.capture(e, path='/signup', method='POST')
            except Exception:
                pass
            print(f'  ❌ signup validation failed: {type(e).__name__}: {e}')
            return render_template(
                'admin/signup.html', form=form, slug=slug, base=base,
                error='We could not check that address just now. Please try '
                      'again in a moment — nothing was created.')
        if error:
            return render_template('admin/signup.html', form=form, slug=slug,
                                   base=base, error=error)

        try:
            token = _create_everything(slug, form, password,
                                       attribution=_came_from())
        except SlugTaken:
            return render_template(
                'admin/signup.html', form=form, slug=slug, base=base,
                error=f'"{slug}" was just taken. Please choose another address.')
        except Exception as e:
            print(f'  ❌ signup failed for {slug!r}: {type(e).__name__}: {e}')
            import traceback; traceback.print_exc()
            try:
                import errors
                errors.capture(e, path='/signup', method='POST')
            except Exception:
                pass
            return render_template(
                'admin/signup.html', form=form, slug=slug, base=base,
                error='We could not finish setting your account up. Please try '
                      'again. If it happens twice, tell us so we can investigate.')

        _tell_us(slug, form, base)
        scheme = 'http' if base.startswith('localhost') else 'https'
        # Where they came from is recorded on the company now; a second
        # company opened from this browser should not inherit the first's link.
        import attribution
        from flask import after_this_request
        after_this_request(attribution.forget)
        return redirect(f'{scheme}://{slug}.{base}/welcome/{token}')

    return render_template('admin/signup.html', form=form, slug='', base=base,
                           error=None)


def _tell_us(slug, form, base):
    """Email whoever runs the product that somebody just signed up."""
    try:
        import notifications
        import product
        to = product.support_email()
        if not to:
            return
        url = f'https://{slug}.{base}'
        notifications.send_email(
            to, product.name(),
            f'New signup: {form.get("business") or slug}',
            f'''<p><strong>{form.get('business') or slug}</strong> just signed up.</p>
            <table cellpadding="6" style="border-collapse:collapse;font-family:sans-serif">
              <tr><td><strong>Company</strong></td><td>{form.get('business') or ''}</td></tr>
              <tr><td><strong>Person</strong></td><td>{form.get('name') or ''}</td></tr>
              <tr><td><strong>Email</strong></td><td>{form.get('email') or ''}</td></tr>
              <tr><td><strong>Address</strong></td><td><a href="{url}">{url}</a></td></tr>
            </table>
            <p>They are on the top plan, trialing. The 14 days start when they
            first assign a job to somebody.</p>''',
            from_name=product.name(),
            from_email=product.from_email() or None,
            reply_to=form.get('email') or to,
            api_key=product.resend_api_key() or None)
    except Exception as e:
        print(f'  ⚠️  could not send signup notice for {slug!r}: '
              f'{type(e).__name__}: {e}')


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
    _ensure_control_plane(engine)
    if control_plane.find(engine, slug):
        return f'"{slug}" is already taken. Try another.'
    return None


def _came_from():
    """The link that first brought this browser to the site (attribution.py)."""
    try:
        import attribution
        from flask import current_app
        return attribution.read(request.cookies, current_app.secret_key)
    except Exception:
        return {}


def _create_everything(slug, form, password, attribution=None):
    """Build one tenant completely, under a cross-worker per-slug lock."""
    engine = _engine()
    schema = tenancy.schema_for(slug)

    with _slug_lock(engine, slug):
        _ensure_control_plane(engine)
        if control_plane.find(engine, slug):
            raise SlugTaken(slug)
        if provisioning.schema_exists(engine, schema):
            raise RuntimeError(
                f'unregistered tenant schema {schema!r} already exists; '
                'refusing to overwrite it')

        created_schema = False
        created_org = False
        try:
            provisioning.create_schema(engine, schema)
            created_schema = True
            provisioning.migrate_schema(engine, schema)

            from flask import current_app
            _seed_strict(current_app, schema)

            with tenancy.use_tenant(schema):
                owner = User(name=form['name'], username=form['email'], role='owner',
                             active=True)
                owner.set_password(password)
                db.session.add(owner)
                db.session.commit()
                from models import BusinessSetting
                BusinessSetting.set('business_name', form['business'])
                BusinessSetting.set('email', form['email'])
                db.session.commit()
                raw, _ = LoginToken.issue(owner, 'signup', email=form['email'])

            control_plane.create(engine, slug, form['business'], form['email'],
                                 attribution=attribution)
            created_org = True
            control_plane.mark_provisioned(engine, slug)
            control_plane.record_tenant_login(engine, form['email'], slug)
            return raw
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            cleanup_errors = []
            if created_org:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(
                            'DELETE FROM public.organizations WHERE slug = :s'),
                            {'s': slug})
                except Exception as cleanup_error:
                    cleanup_errors.append(f'organization: {cleanup_error}')
            if created_schema:
                try:
                    provisioning.drop_schema(engine, schema)
                except Exception as cleanup_error:
                    cleanup_errors.append(f'schema: {cleanup_error}')
            if cleanup_errors:
                print(f'  ❌ incomplete signup cleanup for {slug!r}: '
                      + '; '.join(cleanup_errors))
            raise


def _cleanup(slug):
    """Legacy/manual cleanup helper; never used by the signup exception path."""
    engine = _engine()
    schema = tenancy.schema_for(slug)
    with _slug_lock(engine, slug):
        if control_plane.find(engine, slug):
            raise RuntimeError(f'refusing to clean up registered tenant {slug!r}')
        if provisioning.schema_exists(engine, schema):
            provisioning.drop_schema(engine, schema)


@signup_bp.route('/welcome/<token>')
def welcome(token):
    """Spend the signup token and start the session, on the company's own host."""
    if not tenancy.is_tenant():
        return redirect(url_for('signup.signup') if signups_open() else '/')

    user = LoginToken.consume(token, 'signup')
    if not user:
        return render_template('admin/welcome_expired.html')

    session.clear()
    session.permanent = True
    # Delegates to the one shared helper (also used by auth.authenticate())
    # rather than hand-assigning session keys, so this can't again silently
    # drift out of sync with what a real login sets -- see JOURNEY-01.
    bind_authenticated_session(user)
    return redirect(url_for('settings.getting_started'))
