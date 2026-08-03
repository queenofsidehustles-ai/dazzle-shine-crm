from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required, owner_required
from models import PricingSetting, BusinessSetting, Prospect
from extensions import db
from pricing import SERVICES, EXTRAS, DEPOSIT_AMOUNT

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')


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
        for key in ('sqft_surcharge', 'sqft_hours'):
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
              'interview_calendar_link', 'bgcheck_provider_url', 'bgcheck_provider_name']
    if request.method == 'POST':
        for f in fields:
            BusinessSetting.set(f, request.form.get(f, ''))
        db.session.commit()
        flash('Business settings updated!', 'success')
        return redirect(url_for('settings.business'))

    current = {f: BusinessSetting.get(f) for f in fields}
    if not current['worker_model']:
        current['worker_model'] = 'contractor'
    if not current['reception_model']:
        current['reception_model'] = 'va'
    return render_template('admin/settings_business.html', current=current)
