import json
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from models import Staff, ContractorApplication, Booking
from extensions import db
from notifications import send_email

contractors_bp = Blueprint('contractors', __name__, url_prefix='/contractors')

EXP_LEVELS = [
    ('new',         'New Cleaner',   40),
    ('experienced', 'Experienced',   45),
    ('senior',      'Senior',        50),
]


# ── Applications ───────────────────────────────────────────────────────────────

@contractors_bp.route('/applications')
@login_required
def applications():
    status_filter = request.args.get('status', '')
    q = ContractorApplication.query.order_by(ContractorApplication.created_at.desc())
    if status_filter:
        q = q.filter_by(status=status_filter)
    apps = q.all()
    counts = {
        'all': ContractorApplication.query.count(),
        'new': ContractorApplication.query.filter_by(status='new').count(),
        'reviewing': ContractorApplication.query.filter_by(status='reviewing').count(),
        'hired': ContractorApplication.query.filter_by(status='hired').count(),
        'rejected': ContractorApplication.query.filter_by(status='rejected').count(),
    }
    return render_template('admin/applications.html', apps=apps,
                           counts=counts, status_filter=status_filter)


@contractors_bp.route('/applications/<int:app_id>', methods=['GET', 'POST'])
@login_required
def application_detail(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    if request.method == 'POST':
        a.status = request.form.get('status', a.status)
        a.admin_notes = request.form.get('admin_notes', a.admin_notes)
        db.session.commit()
        flash('Application updated.', 'success')
        if a.status == 'hired':
            return redirect(url_for('contractors.hire', app_id=app_id))
        return redirect(url_for('contractors.application_detail', app_id=app_id))
    return render_template('admin/application_detail.html', a=a)


@contractors_bp.route('/applications/<int:app_id>/hire', methods=['POST'])
@login_required
def hire(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    exp = request.form.get('experience_level', 'new')
    pay_type = request.form.get('pay_type', 'percent')
    pay_rate = float(request.form.get('pay_rate', 40))
    default_color = '#7c3aed'
    s = Staff(
        name=a.name, email=a.email, phone=a.phone,
        pay_type=pay_type, pay_rate=pay_rate, experience_level=exp,
        has_transportation=a.has_transportation,
        has_supplies=a.has_supplies,
        color=default_color, is_active=True,
    )
    db.session.add(s)
    a.status = 'hired'
    db.session.commit()
    flash(f'{a.name} has been added to your team!', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=s.id))


# ── Team / Contractor Profiles ─────────────────────────────────────────────────

@contractors_bp.route('/team')
@login_required
def team():
    staff = Staff.query.order_by(Staff.is_active.desc(), Staff.name).all()
    return render_template('admin/team.html', staff=staff, exp_levels=EXP_LEVELS)


@contractors_bp.route('/team/<int:staff_id>', methods=['GET', 'POST'])
@login_required
def staff_detail(staff_id):
    s = Staff.query.get_or_404(staff_id)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'toggle_onboarding':
            step_key = request.form.get('step')
            steps = s.get_onboarding()
            if step_key in steps:
                steps.remove(step_key)
            else:
                steps.append(step_key)
            s.onboarding_steps = json.dumps(steps)
            db.session.commit()
            return jsonify({'ok': True, 'completed': steps})
        # Full profile update
        s.name = request.form.get('name', s.name).strip()
        s.phone = request.form.get('phone', s.phone or '').strip()
        s.email = request.form.get('email', s.email or '').strip()
        s.experience_level = request.form.get('experience_level', s.experience_level)
        s.pay_type = request.form.get('pay_type', s.pay_type)
        s.pay_rate = float(request.form.get('pay_rate', s.pay_rate or 40))
        s.emergency_contact_name = request.form.get('emergency_contact_name', '').strip()
        s.emergency_contact_phone = request.form.get('emergency_contact_phone', '').strip()
        s.has_transportation = 'has_transportation' in request.form
        s.has_supplies = 'has_supplies' in request.form
        s.color = request.form.get('color', s.color)
        s.is_active = 'is_active' in request.form
        s.notes = request.form.get('notes', '').strip()
        db.session.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('contractors.staff_detail', staff_id=staff_id))
    recent_jobs = Booking.query.filter_by(assigned_cleaner=s.name, status='completed').order_by(Booking.created_at.desc()).limit(10).all()
    return render_template('admin/contractor_detail.html', s=s, recent_jobs=recent_jobs, exp_levels=EXP_LEVELS)


# ── Payroll ────────────────────────────────────────────────────────────────────

@contractors_bp.route('/payroll')
@login_required
def payroll():
    today = date.today()
    # Default: this week (Mon-Sun)
    week_start_str = request.args.get('start', (today - timedelta(days=today.weekday())).isoformat())
    week_end_str = request.args.get('end', (today - timedelta(days=today.weekday()) + timedelta(days=6)).isoformat())

    jobs = Booking.query.filter(
        Booking.preferred_date >= week_start_str,
        Booking.preferred_date <= week_end_str,
        Booking.status == 'completed',
        Booking.assigned_cleaner != None,
        Booking.assigned_cleaner != '',
    ).all()

    staff_all = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    staff_map = {s.name: s for s in staff_all}

    payroll_data = {}
    for job in jobs:
        name = job.assigned_cleaner
        s = staff_map.get(name)
        if not s:
            continue
        earned = s.calc_pay(job_price=job.price or 0, hours_worked=job.hours_worked or 0)
        if name not in payroll_data:
            payroll_data[name] = {'staff': s, 'jobs': [], 'total': 0}
        payroll_data[name]['jobs'].append({'booking': job, 'earned': earned})
        payroll_data[name]['total'] += earned

    grand_total = sum(v['total'] for v in payroll_data.values())
    return render_template('admin/payroll.html',
        payroll=payroll_data, grand_total=round(grand_total, 2),
        week_start=week_start_str, week_end=week_end_str,
    )


# ── Public application form ────────────────────────────────────────────────────

@contractors_bp.route('/apply', methods=['GET', 'POST'])
def apply():
    if request.method == 'POST':
        a = ContractorApplication(
            name=request.form.get('name', '').strip(),
            email=request.form.get('email', '').strip(),
            phone=request.form.get('phone', '').strip(),
            years_experience=request.form.get('years_experience', ''),
            services=', '.join(request.form.getlist('services')),
            availability=', '.join(request.form.getlist('availability')),
            has_transportation='has_transportation' in request.form,
            has_supplies='has_supplies' in request.form,
            has_references='has_references' in request.form,
            background_check_consent='background_check_consent' in request.form,
            agrees_to_ic_terms='agrees_to_ic_terms' in request.form,
            why_interested=request.form.get('why_interested', '').strip(),
            status='new',
        )
        db.session.add(a)
        db.session.commit()
        notify = __import__('os').environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
        send_email(
            to_email=notify, to_name='Dazzle & Shine Maids',
            from_name='Dazzle & Shine Hiring',
            subject=f'New Cleaner Application: {a.name}',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">New Contractor Application</h2>
  <p><strong>Name:</strong> {a.name}</p>
  <p><strong>Email:</strong> {a.email} &nbsp; <strong>Phone:</strong> {a.phone}</p>
  <p><strong>Experience:</strong> {a.years_experience} years</p>
  <p><strong>Services:</strong> {a.services}</p>
  <p><strong>Availability:</strong> {a.availability}</p>
  <p><strong>Has car:</strong> {'Yes' if a.has_transportation else 'No'} &nbsp;
     <strong>Has supplies:</strong> {'Yes' if a.has_supplies else 'No'}</p>
  <p><strong>Why interested:</strong> {a.why_interested or '—'}</p>
</div>""",
        )
        return render_template('public/apply_done.html', name=a.name)
    return render_template('public/apply.html')
