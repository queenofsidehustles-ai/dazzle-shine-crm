from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required, owner_required
from models import PricingSetting, BusinessSetting, Prospect
from extensions import db
from pricing import SERVICES, EXTRAS, DEPOSIT_AMOUNT
import branding

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')


@settings_bp.route('/brand/<key>', methods=['POST'])
@login_required
def switch_brand(key):
    """Point the CRM at one side of the business, or at all of it.

    A view preference, so it lives in the session rather than the database —
    two people can be looking at different brands at the same time without
    fighting over a setting. Returns you to the page you were on.
    """
    import brands
    brands.set_active(key)
    nxt = request.form.get('next') or request.referrer or url_for('admin.dashboard')
    # Only ever bounce back inside this app.
    return redirect(nxt if nxt.startswith('/') else url_for('admin.dashboard'))


@settings_bp.route('/setup')
@owner_required
def setup():
    """The 'what's left to do' list for a business that has just been handed
    its CRM."""
    import onboarding
    return render_template('admin/setup.html', s=onboarding.summary())


@settings_bp.route('/setup/confirm/<key>', methods=['POST'])
@owner_required
def setup_confirm(key):
    """Mark one of the read-and-approve steps as done.

    Pricing and terms can't be detected — a business might legitimately keep a
    default price or a default clause. So the owner ticks these herself, which
    also makes it an explicit act rather than something that quietly passed."""
    labels = {'pricing_reviewed': 'Prices', 'terms_reviewed': 'Customer terms'}
    if key not in labels:
        flash('Unknown step.', 'error')
        return redirect(url_for('settings.setup'))
    BusinessSetting.set(key, '1')
    db.session.commit()
    flash(f'{labels[key]} marked as reviewed.', 'success')
    return redirect(url_for('settings.setup'))


@settings_bp.route('/automations')
@owner_required
def automations_page():
    """Whether the scheduled jobs are alive.

    They run outside the app, so their silence is indistinguishable from there
    being nothing to do. This is the page that tells the difference."""
    import automations as _auto
    from models import CronRun
    first = CronRun.query.order_by(CronRun.ran_at.asc()).first()
    return render_template('admin/automations.html',
                           data=_auto.summary(),
                           base=branding.crm_base(),
                           tracking_since=(first.ran_at.strftime('%b %-d, %Y')
                                           if first else 'when this page shipped'))


@settings_bp.route('/connections', methods=['GET', 'POST'])
@owner_required
def connections():
    """Where an owner connects her own Stripe, texting and email accounts.

    The point of this page is that nobody else has to be involved. Before it
    existed these keys could only be set by whoever had the hosting dashboard,
    which made that person a permanent dependency for every business using the
    CRM — and left them holding other people's payment credentials."""
    import integrations
    if request.method == 'POST':
        saved = []
        for name, (_env, label, is_secret) in integrations.FIELDS.items():
            if name not in request.form:
                continue
            value = (request.form.get(name) or '').strip()
            # A secret is shown back masked. If it comes back unchanged, the
            # owner didn't retype it — leave the stored key alone rather than
            # overwriting a working key with a row of dots.
            if is_secret and value and '…' in value:
                continue
            if value or request.form.get(f'clear_{name}'):
                integrations.set(name, value)
                saved.append(label)
        flash(f"Saved: {', '.join(saved)}." if saved else 'Nothing changed.', 'success')
        return redirect(url_for('settings.connections'))

    fields = {n: {'label': lbl, 'secret': sec, 'value': integrations.masked(n),
                  'source': integrations.source(n)}
              for n, (_e, lbl, sec) in integrations.FIELDS.items()}
    return render_template('admin/settings_connections.html',
                           fields=fields, status=integrations.status())


@settings_bp.route('/connections/test-stripe', methods=['POST'])
@owner_required
def test_stripe():
    """Ask Stripe who we are. Proves the key works and, more importantly, shows
    WHICH account it reaches — the expensive mistake is a key that works fine but
    belongs to somebody else's business."""
    import integrations, stripe
    key = integrations.stripe_secret_key()
    if not key:
        flash('No Stripe secret key saved yet.', 'warning')
        return redirect(url_for('settings.connections'))
    stripe.api_key = key
    try:
        acct = stripe.Account.retrieve()
        name = (acct.get('business_profile') or {}).get('name') or acct.get('email') or acct.get('id')
        mode = integrations.stripe_mode()
        if mode == 'test':
            flash(f'Connected to "{name}" in TEST mode. Real cards will not be '
                  f'charged until you paste your live key.', 'warning')
        else:
            flash(f'Connected to "{name}" — live payments will reach this account. '
                  f'Check that name is your business.', 'success')
    except Exception as e:
        flash(f'Stripe rejected that key: {e}', 'error')
    return redirect(url_for('settings.connections'))


@settings_bp.route('/commercial', methods=['GET', 'POST'])
@owner_required
def commercial():
    import commercial_pricing as cp
    if request.method == 'POST':
        PricingSetting.set('comm_hourly_cost', request.form.get('comm_hourly_cost') or 20)
        try:
            pct = float(request.form.get('comm_target_labor') or 40)
        except ValueError:
            pct = 40
        PricingSetting.set('comm_target_labor', round(pct / 100.0, 4))
        PricingSetting.set('comm_min_visit', request.form.get('comm_min_visit') or 80)
        for c in cp.PROD_RATES:
            v = request.form.get(f'comm_prod_{c}')
            if v:
                PricingSetting.set(f'comm_prod_{c}', v)
        db.session.commit()
        flash('Commercial pricing updated.', 'success')
        return redirect(url_for('settings.commercial'))
    return render_template('admin/settings_commercial.html',
                           cfg=cp.get_config(), category_labels=Prospect.CATEGORY_LABELS)


@settings_bp.route('/followup-texts', methods=['GET', 'POST'])
@owner_required
def followup_texts():
    """The wording of the Google Ads follow-up texts.

    In settings rather than in the code because the right words here are not a
    programming question — she is the one reading the replies, and waiting on a
    deploy to change a sentence would mean the wording never actually improves."""
    import lsa
    if request.method == 'POST':
        for track, _label in lsa.TRACKS:
            for step in (1, 2, 3):
                lsa.save_template(track, step,
                                  request.form.get(f'msg_{track}_{step}', ''))
        flash('Follow-up texts saved. Anyone mid-sequence gets the new wording '
              'from their next message on.', 'success')
        return redirect(url_for('settings.followup_texts'))

    messages = {(t, s): lsa.template_for(t, s)
                for t, _l in lsa.TRACKS for s in (1, 2, 3)}
    edited = {(t, s): messages[(t, s)].strip() != lsa.DEFAULT_MESSAGES[(t, s)].strip()
              for t, _l in lsa.TRACKS for s in (1, 2, 3)}
    return render_template('admin/settings_followup_texts.html',
                           tracks=lsa.TRACKS, messages=messages, edited=edited,
                           days=[d for d, _n in lsa.SEQUENCE])


@settings_bp.route('/pricing', methods=['GET', 'POST'])
@owner_required
def pricing():
    from pricing import get_labor_rate, LABOR_RATE_DEFAULT
    if request.method == 'POST':
        # Save deposit
        PricingSetting.set('deposit_amount', request.form.get('deposit_amount', DEPOSIT_AMOUNT))

        # What a cleaner earns per person-hour — the basis for all job pay.
        rate = (request.form.get('labor_rate') or '').strip()
        if rate:
            PricingSetting.set('labor_rate', rate)

        # Bigger-home surcharge: price and the time it adds
        for key in ('sqft_surcharge', 'sqft_hours', 'max_labor_pct', 'tip_fee_pct'):
            val = request.form.get(key)
            if val not in (None, ''):     # 0 is a legitimate answer
                PricingSetting.set(key, val)

        # Save service prices
        for svc_key in SERVICES:
            for field in ('base', 'per_extra_bed', 'per_extra_bath'):
                form_key = f"{svc_key}_{field}"
                val = request.form.get(form_key)
                if val:
                    PricingSetting.set(form_key, val)

        # Save extras — price and the time each one takes
        for extra_name in EXTRAS:
            slug = extra_name.lower().replace(' ', '_')
            val = request.form.get(f'extra_{slug}')
            if val:
                PricingSetting.set(f'extra_{slug}', val)
            hrs = request.form.get(f'extrahrs_{slug}')
            if hrs not in (None, ''):     # 0 is a legitimate answer here
                PricingSetting.set(f'extrahrs_{slug}', hrs)

        db.session.commit()
        flash('Pricing updated successfully!', 'success')
        return redirect(url_for('settings.pricing'))

    # Build current values (DB overrides defaults)
    current = {}
    current['deposit_amount'] = PricingSetting.get('deposit_amount', DEPOSIT_AMOUNT)
    current['labor_rate'] = get_labor_rate()
    from pricing import get_sqft_surcharge_rate, get_sqft_hours_rate
    current['sqft_surcharge'] = get_sqft_surcharge_rate()
    current['sqft_hours'] = get_sqft_hours_rate()
    from pricing import get_max_labor_percent, get_tip_fee_percent
    current['max_labor_pct'] = get_max_labor_percent()
    current['tip_fee_pct'] = get_tip_fee_percent()
    for svc_key, svc in SERVICES.items():
        for field in ('base', 'per_extra_bed', 'per_extra_bath'):
            form_key = f"{svc_key}_{field}"
            current[form_key] = PricingSetting.get(form_key, svc[field])
    from pricing import get_extra_hours
    for extra_name, price in EXTRAS.items():
        slug = extra_name.lower().replace(' ', '_')
        current[f'extra_{slug}'] = PricingSetting.get(f'extra_{slug}', price)
        current[f'extrahrs_{slug}'] = get_extra_hours(extra_name)

    return render_template('admin/settings_pricing.html',
                           services=SERVICES, extras=EXTRAS,
                           current=current)


@settings_bp.route('/business', methods=['GET', 'POST'])
@owner_required
def business():
    fields = ['business_name', 'phone', 'email', 'address', 'city', 'state', 'zip_code', 'website',
              'worker_model', 'reception_model', 'agreement_template',
              'interview_calendar_link', 'bgcheck_provider_url', 'bgcheck_provider_name',
              'customer_terms',
              # Branding — what customers see on emails, quotes and review prompts.
              'google_review_link', 'content_business_description',
              'timezone', 'charge_hour',
              'brand_tagline', 'brand_dark', 'brand_accent', 'brand_accent_text',
              'brand_domain_verified',
              # An optional second trading name for commercial work.
              'commercial_name', 'commercial_tagline', 'commercial_from_email',
              'commercial_reply_to', 'commercial_phone', 'commercial_website',
              'commercial_dark', 'commercial_accent', 'commercial_accent_text',
              'commercial_domain_verified']
    if request.method == 'POST':
        # Save only the fields this particular form actually submitted. The page
        # has several separate forms, and writing every field on every save
        # would blank out whichever card the owner wasn't looking at.
        for f in fields:
            if f in request.form:
                BusinessSetting.set(f, request.form.get(f, ''))
        db.session.commit()
        # Typing the original business name back in is enough to trigger the
        # one-time restore of its commercial brand, palette and review link —
        # no redeploy needed.
        import legacy_brands
        legacy_brands.restore_if_original()
        flash('Business settings updated!', 'success')
        return redirect(url_for('settings.business'))

    current = {f: BusinessSetting.get(f) for f in fields}
    if not current.get('customer_terms'):
        import customer_terms as _ct
        current['customer_terms'] = _ct.DEFAULT_TERMS
    if not current['worker_model']:
        current['worker_model'] = 'contractor'
    if not current['reception_model']:
        current['reception_model'] = 'va'
    return render_template('admin/settings_business.html', current=current)


# ── What has broken lately ──────────────────────────────────────────────────

@settings_bp.route('/errors')
@owner_required
def errors_page():
    """Faults the CRM has reported about itself.

    Owner-only: a traceback names files, functions and sometimes the shape of
    the data, which is more of the inside of the business than a VA needs."""
    from models import ErrorLog
    show_resolved = request.args.get('show') == 'resolved'
    q = ErrorLog.query.filter(ErrorLog.kind != 'blocked')
    q = q.filter_by(resolved=True) if show_resolved else q.filter_by(resolved=False)
    rows = q.order_by(ErrorLog.last_seen.desc()).limit(100).all()
    blocked = (ErrorLog.query.filter_by(kind='blocked')
               .order_by(ErrorLog.last_seen.desc()).limit(20).all())
    open_count = ErrorLog.query.filter_by(resolved=False).filter(
        ErrorLog.kind != 'blocked').count()
    return render_template('admin/errors.html', rows=rows, blocked=blocked,
                           show_resolved=show_resolved, open_count=open_count)


@settings_bp.route('/errors/<int:error_id>/resolve', methods=['POST'])
@owner_required
def resolve_error(error_id):
    """Tick one off. If it happens again it comes straight back — see
    ErrorLog.record — so this is 'I have looked at this', not 'be quiet'."""
    from models import ErrorLog
    from extensions import db
    row = ErrorLog.query.get_or_404(error_id)
    row.resolved = not row.resolved
    db.session.commit()
    flash('Marked as sorted. It will reappear if it happens again.'
          if row.resolved else 'Reopened.', 'success')
    return redirect(url_for('settings.errors_page'))
