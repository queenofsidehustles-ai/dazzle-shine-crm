import json
import secrets
import threading
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from auth import login_required
from models import Staff, ContractorApplication, Booking, BusinessSetting
from extensions import db
from notifications import send_email

contractors_bp = Blueprint('contractors', __name__, url_prefix='/contractors')

EXP_LEVELS = [
    ('standard', 'Starting Rate', 50),
    ('top',      'Top Performer', 55),
]


@contractors_bp.route('/email-test')
@login_required
def email_test():
    """Diagnostic: send a real test email and show exactly what Resend says."""
    import os as _os
    to = request.args.get('to') or BusinessSetting.get('email') or \
        _os.environ.get('OWNER_EMAIL', 'dazzleandshinemaids@gmail.com')
    from_email = _os.environ.get('FROM_EMAIL', 'bookings@dazzleandshinemaids.com')
    has_key = bool(_os.environ.get('RESEND_API_KEY'))

    ok, detail = send_email(
        to_email=to, to_name='Dazzle & Shine',
        subject='✅ Dazzle & Shine — Email Test',
        html='<div style="font-family:sans-serif;padding:24px">'
             '<h2 style="color:#1f1333">Your email is working! 🎉</h2>'
             '<p>If you can read this, Dazzle &amp; Shine emails are sending correctly.</p></div>',
    )

    color = '#155724' if ok else '#842029'
    bg = '#d4edda' if ok else '#f8d7da'
    fix_hint = '' if ok else (
        '<div style="margin-top:18px;padding:16px;background:#fff8e1;border:1px solid #f0d488;border-radius:8px;color:#7c4a04;font-size:0.9rem;line-height:1.6">'
        '<strong>How to fix:</strong><br>'
        '1. In Railway, make sure <code>RESEND_API_KEY</code> is set'
        f' (currently {"SET" if has_key else "<strong>MISSING</strong>"}).<br>'
        f'2. In your Resend account, verify the sending domain for <code>{from_email}</code>'
        ' (Resend → Domains → Add/Verify). Until the domain is verified, Resend rejects sends.<br>'
        '3. Re-run this test.</div>'
    )
    return (
        f'<div style="font-family:sans-serif;max-width:600px;margin:40px auto;padding:0 16px">'
        f'<div style="background:{bg};color:{color};padding:18px 22px;border-radius:10px;font-weight:700;font-size:1.05rem">'
        f'{"✅ Test email sent!" if ok else "❌ Email did NOT send"}</div>'
        f'<p style="margin-top:16px;color:#1f1333"><strong>To:</strong> {to}<br>'
        f'<strong>From:</strong> {from_email}<br>'
        f'<strong>API key set:</strong> {"yes" if has_key else "no"}<br>'
        f'<strong>Result:</strong> {detail}</p>'
        f'{fix_hint}'
        f'<p style="margin-top:20px"><a href="{url_for("contractors.team")}" style="color:#7c3aed">← Back to Team</a></p>'
        f'</div>'
    )


# ── Applications ───────────────────────────────────────────────────────────────

SOURCES = ['Indeed', 'Facebook', 'Nextdoor', 'Craigslist', 'Referral', 'Walk-in', 'Website', 'Other']


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
    apply_url = url_for('contractors.apply', _external=True)
    return render_template('admin/applications.html', apps=apps,
                           counts=counts, status_filter=status_filter,
                           apply_url=apply_url, sources=SOURCES)


@contractors_bp.route('/applications/add', methods=['POST'])
@login_required
def add_applicant():
    name  = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    if not name or not email:
        flash('Name and email are required.', 'error')
        return redirect(url_for('contractors.applications'))
    a = ContractorApplication(
        name=name, email=email, phone=phone,
        years_experience=request.form.get('years_experience', ''),
        availability=request.form.get('availability', ''),
        has_transportation=request.form.get('has_transportation') == 'on',
        admin_notes=f"Source: {request.form.get('source','Other')}\n{request.form.get('notes','').strip()}",
        status='new',
    )
    db.session.add(a)
    db.session.commit()
    flash(f'{name} added. Send them the application link to complete their profile.', 'success')
    return redirect(url_for('contractors.application_detail', app_id=a.id))


@contractors_bp.route('/applications/<int:app_id>/send-link', methods=['POST'])
@login_required
def send_application_link(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    import os
    biz = BusinessSetting.get('business_name') or os.environ.get('BUSINESS_NAME', 'Dazzle & Shine Maids')
    apply_url = url_for('contractors.apply', _external=True)
    send_email(
        to_email=a.email, to_name=a.name,
        from_name=f'{biz} Hiring',
        subject=f'Complete your application — {biz}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;margin:0;font-size:1.5rem">We'd Love to Meet You!</h1>
    <p style="color:#c9b8e8;margin:8px 0 0;font-size:0.9rem">{biz} — Hiring</p>
  </div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e4dfef;border-top:none">
    <p>Hi {a.name.split()[0]},</p>
    <p style="margin:12px 0">We saw your interest in joining our team and we'd love to learn more about you! Please take 2 minutes to complete our application form:</p>
    <div style="text-align:center;margin:24px 0">
      <a href="{apply_url}" style="background:#d3a84f;color:#1f1333;padding:13px 28px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;display:inline-block">
        Complete My Application →
      </a>
    </div>
    <p style="font-size:0.85rem;color:#9a95ad">Link not working? Copy and paste: {apply_url}</p>
    <p style="margin-top:16px">Questions? Just reply to this email.<br>
    <strong style="color:#b98a33">{biz}</strong></p>
  </div>
</div>""",
    )
    flash(f'Application link sent to {a.email}!', 'success')
    return redirect(url_for('contractors.application_detail', app_id=app_id))


@contractors_bp.route('/applications/<int:app_id>/send-interview-invite', methods=['POST'])
@login_required
def send_interview_invite(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    import os
    biz = BusinessSetting.get('business_name') or os.environ.get('BUSINESS_NAME', 'Dazzle & Shine Maids')
    cal_link = BusinessSetting.get('interview_calendar_link', '')
    if not cal_link:
        flash('Add your calendar link in Settings → Business first.', 'warning')
        return redirect(url_for('contractors.application_detail', app_id=app_id))
    send_email(
        to_email=a.email, to_name=a.name,
        from_name=f'{biz} Hiring',
        subject=f'Next Step: Schedule Your Phone Interview — {biz}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;margin:0;font-size:1.5rem">You're Moving Forward! 🎉</h1>
    <p style="color:#c9b8e8;margin:8px 0 0;font-size:0.9rem">{biz} — Hiring</p>
  </div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e4dfef;border-top:none">
    <p>Hi {a.name.split()[0]},</p>
    <p style="margin:12px 0">We reviewed your application and we'd love to chat! Please use the link below to pick a time for a quick phone interview (about 10–15 minutes).</p>
    <div style="text-align:center;margin:24px 0">
      <a href="{cal_link}" style="background:#d3a84f;color:#1f1333;padding:13px 28px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;display:inline-block">
        Pick My Interview Time →
      </a>
    </div>
    <p style="font-size:0.85rem;color:#5f5878">The call will cover your experience, availability, and any questions you have about the position. It's quick and easy!</p>
    <p style="font-size:0.85rem;color:#9a95ad">Link not working? Copy and paste: {cal_link}</p>
    <p style="margin-top:16px">Looking forward to speaking with you!<br>
    <strong style="color:#b98a33">{biz}</strong></p>
  </div>
</div>""",
    )
    a.interview_invite_sent_at = datetime.utcnow()
    db.session.commit()
    flash(f'Interview invite sent to {a.email}!', 'success')
    return redirect(url_for('contractors.application_detail', app_id=app_id))


@contractors_bp.route('/applications/<int:app_id>/send-spanish-interview', methods=['POST'])
@login_required
def send_spanish_interview(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    import os
    biz = BusinessSetting.get('business_name') or os.environ.get('BUSINESS_NAME', 'Dazzle & Shine Maids')
    owner_email = BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL', 'dazzleandshinemaids@gmail.com')
    send_email(
        to_email=a.email, to_name=a.name,
        from_name=f'{biz} Contrataciones',
        subject=f'Preguntas de Entrevista — {biz}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;margin:0;font-size:1.5rem">¡Gracias por su interés! 🌟</h1>
    <p style="color:#c9b8e8;margin:8px 0 0;font-size:0.9rem">{biz} — Contrataciones</p>
  </div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e4dfef;border-top:none">
    <p>Hola {a.name.split()[0]},</p>
    <p style="margin:12px 0">Hemos revisado su solicitud y nos gustaría conocerle mejor. Por favor responda las siguientes preguntas por correo electrónico y le contactaremos pronto.</p>
    <div style="background:#f6f5fb;border-radius:10px;padding:20px;margin:20px 0;line-height:2.2">
      <strong style="color:#3b2460">Preguntas de Entrevista:</strong><br><br>
      <strong>1.</strong> ¿Cuánta experiencia tiene limpiando casas o negocios?<br>
      <strong>2.</strong> ¿Tiene transporte propio confiable para llegar a los trabajos?<br>
      <strong>3.</strong> ¿Tiene sus propios materiales y equipos de limpieza?<br>
      <strong>4.</strong> ¿Qué días y horarios está disponible para trabajar?<br>
      <strong>5.</strong> ¿Puede proporcionar 1–2 referencias de empleos anteriores (nombre y teléfono)?<br>
      <strong>6.</strong> ¿Tiene alguna pregunta sobre el puesto o el pago?
    </div>
    <p style="font-size:0.9rem;color:#5f5878">Responda a este correo electrónico con sus respuestas. <strong>Nos comunicaremos con usted dentro de 2 días hábiles.</strong></p>
    <p style="margin-top:16px">¡Gracias y esperamos escuchar de usted pronto!<br>
    <strong style="color:#b98a33">{biz}</strong><br>
    <a href="mailto:{owner_email}" style="color:#7c3aed">{owner_email}</a></p>
  </div>
</div>""",
    )
    a.interview_invite_sent_at = datetime.utcnow()
    db.session.commit()
    flash(f'Spanish interview questions sent to {a.email}!', 'success')
    return redirect(url_for('contractors.application_detail', app_id=app_id))


@contractors_bp.route('/applications/<int:app_id>/send-bgcheck-request', methods=['POST'])
@login_required
def send_bgcheck_request(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    import os
    biz = BusinessSetting.get('business_name') or os.environ.get('BUSINESS_NAME', 'Dazzle & Shine Maids')
    owner_email = BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL', 'dazzleandshinemaids@gmail.com')
    provider_url = BusinessSetting.get('bgcheck_provider_url', '')
    provider_name = BusinessSetting.get('bgcheck_provider_name', 'the provider below')
    if not provider_url:
        flash('Add a background check provider URL in Settings → Business first.', 'warning')
        return redirect(url_for('contractors.application_detail', app_id=app_id))
    send_email(
        to_email=a.email, to_name=a.name,
        from_name=f'{biz} Hiring',
        subject=f'Action Required: Background Check — {biz}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;margin:0;font-size:1.4rem">Background Check Required</h1>
    <p style="color:#c9b8e8;margin:8px 0 0;font-size:0.9rem">{biz} — Final Step Before Hire</p>
  </div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e4dfef;border-top:none">
    <p>Hi {a.name.split()[0]},</p>
    <p style="margin:12px 0">Great news — you've passed your phone interview! The final step before we can bring you on board is a <strong>background check</strong>.</p>
    <div style="background:#fff3cd;border-radius:10px;padding:16px;margin:20px 0;border-left:4px solid #d3a84f">
      <p style="margin:0;font-weight:700;color:#856404">What you need to do:</p>
      <ol style="margin:10px 0 0;line-height:2;color:#856404">
        <li>Click the button below to visit {provider_name}</li>
        <li>Complete the background check and pay the fee directly on their site</li>
        <li>Email your results/certificate to <strong>{owner_email}</strong></li>
      </ol>
    </div>
    <div style="text-align:center;margin:24px 0">
      <a href="{provider_url}" style="background:#d3a84f;color:#1f1333;padding:13px 28px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;display:inline-block">
        Complete My Background Check →
      </a>
    </div>
    <p style="font-size:0.82rem;color:#9a95ad">This fee is paid directly by you as part of the contractor application process. It ensures the safety of our clients and their homes.</p>
    <p style="margin-top:16px">Once we receive your results, we'll be in touch within 1–2 business days!<br>
    <strong style="color:#b98a33">{biz}</strong></p>
  </div>
</div>""",
    )
    a.bgcheck_request_sent_at = datetime.utcnow()
    a.background_check_status = 'requested'
    db.session.commit()
    flash(f'Background check request sent to {a.email}!', 'success')
    return redirect(url_for('contractors.application_detail', app_id=app_id))


@contractors_bp.route('/applications/<int:app_id>/send-rejection', methods=['POST'])
@login_required
def send_rejection(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    import os
    biz = BusinessSetting.get('business_name') or os.environ.get('BUSINESS_NAME', 'Dazzle & Shine Maids')
    send_email(
        to_email=a.email, to_name=a.name,
        from_name=f'{biz} Hiring',
        subject=f'Your Application — {biz}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;margin:0;font-size:1.4rem">Thank You for Applying</h1>
    <p style="color:#c9b8e8;margin:8px 0 0;font-size:0.9rem">{biz}</p>
  </div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e4dfef;border-top:none">
    <p>Hi {a.name.split()[0]},</p>
    <p style="margin:12px 0">Thank you so much for your interest in joining the {biz} team and for taking the time to apply.</p>
    <p style="margin:12px 0">After careful consideration, we've decided to move forward with other candidates at this time. This was a difficult decision — we appreciated getting to know you through the process.</p>
    <p style="margin:12px 0">We encourage you to apply again in the future as our team grows. We wish you all the best in your search!</p>
    <p style="margin-top:20px">Warmly,<br>
    <strong style="color:#b98a33">{biz}</strong></p>
  </div>
</div>""",
    )
    a.status = 'rejected'
    a.rejection_sent_at = datetime.utcnow()
    db.session.commit()
    flash(f'Rejection email sent to {a.name}.', 'success')
    return redirect(url_for('contractors.application_detail', app_id=app_id))


@contractors_bp.route('/applications/<int:app_id>', methods=['GET', 'POST'])
@login_required
def application_detail(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    if request.method == 'POST':
        action = request.form.get('action', 'notes')
        if action == 'interview':
            a.phone_interview_completed = bool(request.form.get('phone_interview_completed'))
            if a.phone_interview_completed and not a.phone_interview_at:
                a.phone_interview_at = datetime.utcnow()
            a.phone_interview_notes = request.form.get('phone_interview_notes', a.phone_interview_notes)
            if a.status == 'new':
                a.status = 'reviewing'
            flash('Phone interview notes saved.', 'success')
        elif action == 'bgcheck':
            a.background_check_status = request.form.get('background_check_status', a.background_check_status)
            a.background_check_notes = request.form.get('background_check_notes', a.background_check_notes)
            a.bgcheck_results_received = bool(request.form.get('bgcheck_results_received'))
            if a.background_check_status == 'ordered' and not a.background_check_at:
                a.background_check_at = datetime.utcnow()
            flash('Background check updated.', 'success')
        elif action == 'references':
            a.ref1_name = request.form.get('ref1_name', '').strip()
            a.ref1_phone = request.form.get('ref1_phone', '').strip()
            a.ref1_notes = request.form.get('ref1_notes', '').strip()
            a.ref1_called = bool(request.form.get('ref1_called'))
            a.ref2_name = request.form.get('ref2_name', '').strip()
            a.ref2_phone = request.form.get('ref2_phone', '').strip()
            a.ref2_notes = request.form.get('ref2_notes', '').strip()
            a.ref2_called = bool(request.form.get('ref2_called'))
            flash('References saved.', 'success')
        else:
            a.status = request.form.get('status', a.status)
            a.admin_notes = request.form.get('admin_notes', a.admin_notes)
            flash('Application updated.', 'success')
        db.session.commit()
        return redirect(url_for('contractors.application_detail', app_id=app_id))
    return render_template('admin/application_detail.html', a=a)


@contractors_bp.route('/applications/<int:app_id>/hire', methods=['POST'])
@login_required
def hire(app_id):
    a = ContractorApplication.query.get_or_404(app_id)
    exp = request.form.get('experience_level', 'standard')
    pay_type = request.form.get('pay_type', 'percent')
    pay_rate = float(request.form.get('pay_rate', 50))
    import os as _os
    worker_model = request.form.get('worker_model',
        BusinessSetting.get('worker_model') or _os.environ.get('WORKER_MODEL', 'contractor'))
    default_color = '#7c3aed'
    s = Staff(
        name=a.name, email=a.email, phone=a.phone,
        pay_type=pay_type, pay_rate=pay_rate, experience_level=exp,
        has_transportation=a.has_transportation,
        has_supplies=a.has_supplies,
        worker_model=worker_model,
        color=default_color, is_active=True,
    )
    token = secrets.token_urlsafe(32)
    s.agreement_token = token
    db.session.add(s)
    a.status = 'hired'
    db.session.commit()

    if s.email:
        import os
        biz = BusinessSetting.get('business_name') or os.environ.get('BUSINESS_NAME', 'Dazzle & Shine Maids')
        owner_email = BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL', 'dazzleandshinemaids@gmail.com')
        sign_url = url_for('contractors.sign_agreement', token=token, _external=True)
        worker_model = BusinessSetting.get('worker_model', 'contractor')
        agreement_label = 'Independent Contractor Agreement' if worker_model == 'contractor' else 'Employment Agreement'
        send_email(
            to_email=s.email, to_name=s.name,
            from_name=f'{biz} Hiring',
            subject=f'Welcome to the {biz} Team, {s.name.split()[0]}!',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:32px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;margin:0;font-size:1.6rem">Welcome to the Team!</h1>
    <p style="color:#c9b8e8;margin:8px 0 0">You've been approved to work with {biz}</p>
  </div>
  <div style="background:#fff;padding:32px;border-radius:0 0 12px 12px;border:1px solid #e4dfef">
    <p style="margin-top:0">Hi {s.name.split()[0]},</p>
    <p>We're excited to have you on board! Here's what happens next:</p>
    <ol style="line-height:2;color:#3b2460">
      <li><strong>Sign your {agreement_label}</strong> — use the button below</li>
      <li><strong>Complete your onboarding forms</strong> — payment info, emergency contact</li>
      <li><strong>Complete orientation training</strong> — review all policies, then confirm</li>
      <li><strong>Shadow job / trial shift</strong> — you'll go out on a job with an experienced team member first</li>
      {'<li><strong>Receive your supply kit</strong> — we will confirm pickup details with you</li>' if worker_model == 'employee' else '<li><strong>First solo job</strong> — bring your own supplies and equipment</li>'}
    </ol>
    <div style="text-align:center;margin:28px 0">
      <a href="{sign_url}" style="background:#d3a84f;color:#1f1333;padding:14px 32px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;display:inline-block">
        Sign My {agreement_label} →
      </a>
    </div>
    <p style="font-size:0.82rem;color:#9a95ad">Link not working? Copy and paste: {sign_url}</p>
    <p>Questions? Reply to this email or call us directly. We're here to set you up for success.</p>
    <p style="margin-bottom:0">Welcome aboard,<br>
    <strong style="color:#b98a33">{biz}</strong><br>
    <a href="mailto:{owner_email}" style="color:#7c3aed">{owner_email}</a></p>
  </div>
</div>""",
        )

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
        s.pay_rate = float(request.form.get('pay_rate', s.pay_rate or 50))
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
            bgcheck_existing_link=request.form.get('bgcheck_existing_link', '').strip(),
            status='new',
        )
        db.session.add(a)
        db.session.commit()

        # ── Notify Monica of new application ──────────────────────────────────
        import os
        notify = os.environ.get('NOTIFY_EMAIL', 'dazzleandshinemaids@gmail.com')
        send_email(
            to_email=notify, to_name='Dazzle & Shine Maids',
            from_name='Dazzle & Shine Hiring',
            subject=f'New Cleaner Application: {a.name}',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">New Contractor Application</h2>
  <p><strong>Name:</strong> {a.name}</p>
  <p><strong>Email:</strong> {a.email} &nbsp; <strong>Phone:</strong> {a.phone}</p>
  <p><strong>Experience:</strong> {a.years_experience}</p>
  <p><strong>Services:</strong> {a.services}</p>
  <p><strong>Availability:</strong> {a.availability}</p>
  <p><strong>Has car:</strong> {'Yes' if a.has_transportation else 'No'} &nbsp;
     <strong>Has supplies:</strong> {'Yes' if a.has_supplies else 'No'}</p>
  <p><strong>Why interested:</strong> {a.why_interested or '—'}</p>
</div>""",
        )

        # ── Auto-filter ────────────────────────────────────────────────────────
        reject_reasons_en = []
        reject_reasons_es = []

        exp = (a.years_experience or '').strip().lower()
        if not exp or exp in ('no experience', 'none', ''):
            reject_reasons_en.append("Prior cleaning experience is required for all contractors.")
            reject_reasons_es.append("Se requiere experiencia previa en limpieza para todos los contratistas.")

        if not a.has_transportation:
            reject_reasons_en.append("Reliable personal transportation is required.")
            reject_reasons_es.append("Se requiere transporte personal confiable.")

        if reject_reasons_en:
            a.status = 'rejected'
            db.session.commit()
            _send_auto_rejection(a, reject_reasons_en, reject_reasons_es)
        else:
            # Passed — schedule interview invite after 10-minute delay
            a.interview_status = 'pending'
            db.session.commit()
            flask_app = current_app._get_current_object()
            t = threading.Timer(600, _delayed_send_invite, args=[flask_app, a.id])
            t.daemon = True
            t.start()

        return render_template('public/apply_done.html', name=a.name)
    return render_template('public/apply.html')


# ── Agreement sign-off (public — no login required) ────────────────────────────

@contractors_bp.route('/sign-agreement/<token>', methods=['GET', 'POST'])
def sign_agreement(token):
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    biz = BusinessSetting.get('business_name', 'Dazzle & Shine Maids')
    worker_model = BusinessSetting.get('worker_model', 'contractor')
    agreement_label = 'Independent Contractor Agreement' if worker_model == 'contractor' else 'Employment Agreement'
    agreement_text = BusinessSetting.get('agreement_template') or _default_agreement(biz, worker_model)

    if s.agreement_signed_at:
        return render_template('public/sign_done.html',
                               s=s, biz=biz, already_signed=True,
                               agreement_label=agreement_label)

    if request.method == 'POST':
        typed_name = request.form.get('signature', '').strip()
        if not typed_name:
            flash('Please type your full name to sign.', 'error')
            return render_template('public/sign_agreement.html',
                                   s=s, biz=biz, agreement_text=agreement_text,
                                   agreement_label=agreement_label)
        s.agreement_signature = typed_name
        s.agreement_signed_at = datetime.utcnow()
        # Generate orientation token for later completion link
        if not s.orientation_token:
            s.orientation_token = secrets.token_urlsafe(32)
        # Auto-complete the agreement onboarding step
        steps = s.get_onboarding()
        if 'ic_agreement' not in steps:
            steps.append('ic_agreement')
            s.onboarding_steps = json.dumps(steps)
        db.session.commit()

        # Auto-fire orientation email with training resources link
        if s.email:
            forms_url = url_for('contractors.onboarding_forms', token=s.agreement_token, _external=True)
            orientation_done_url = url_for('contractors.orientation_complete', token=s.orientation_token, _external=True)
            from notifications import send_triggered_email
            send_triggered_email(
                trigger='cleaner_orientation',
                to_email=s.email,
                to_name=s.name,
                variables={
                    'forms_link': forms_url,
                    'orientation_link': orientation_done_url,
                }
            )

        return render_template('public/sign_done.html',
                               s=s, biz=biz, already_signed=False,
                               agreement_label=agreement_label,
                               forms_url=url_for('contractors.onboarding_forms',
                                                 token=s.agreement_token, _external=True))

    return render_template('public/sign_agreement.html',
                           s=s, biz=biz, agreement_text=agreement_text,
                           agreement_label=agreement_label)


@contractors_bp.route('/team/<int:staff_id>/resend-agreement', methods=['POST'])
@login_required
def resend_agreement(staff_id):
    import os
    s = Staff.query.get_or_404(staff_id)
    if not s.email:
        flash('No email on file for this team member.', 'error')
        return redirect(url_for('contractors.staff_detail', staff_id=staff_id))
    if not s.agreement_token:
        s.agreement_token = secrets.token_urlsafe(32)
        db.session.commit()
    biz = BusinessSetting.get('business_name') or os.environ.get('BUSINESS_NAME', 'Dazzle & Shine Maids')
    worker_model = BusinessSetting.get('worker_model', 'contractor')
    agreement_label = 'Independent Contractor Agreement' if worker_model == 'contractor' else 'Employment Agreement'
    sign_url = url_for('contractors.sign_agreement', token=s.agreement_token, _external=True)
    send_email(
        to_email=s.email, to_name=s.name,
        from_name=f'{biz} Hiring',
        subject=f'Action Required: Sign Your {agreement_label}',
        html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <div style="background:linear-gradient(135deg,#1f1333,#3b2460);padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h2 style="color:#d3a84f;margin:0">Agreement Signature Required</h2>
  </div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e4dfef">
    <p>Hi {s.name.split()[0]},</p>
    <p>We're still waiting on your signed {agreement_label}. Please sign it at your earliest convenience using the link below.</p>
    <div style="text-align:center;margin:24px 0">
      <a href="{sign_url}" style="background:#d3a84f;color:#1f1333;padding:14px 32px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;display:inline-block">
        Sign My {agreement_label} →
      </a>
    </div>
    <p style="font-size:0.82rem;color:#9a95ad">Link: {sign_url}</p>
    <p style="margin-bottom:0">— <strong>{biz}</strong></p>
  </div>
</div>""",
    )
    flash(f'Agreement link resent to {s.email}', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=staff_id))


# ── Welcome Forms (public) ─────────────────────────────────────────────────────

@contractors_bp.route('/onboarding-forms/<token>', methods=['GET', 'POST'])
def onboarding_forms(token):
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    biz = BusinessSetting.get('business_name', 'Dazzle & Shine Maids')

    if s.welcome_forms_at:
        return render_template('public/onboarding_forms_done.html', s=s, biz=biz, already_done=True)

    if request.method == 'POST':
        s.emergency_contact_name = request.form.get('emergency_contact_name', '').strip() or s.emergency_contact_name
        s.emergency_contact_phone = request.form.get('emergency_contact_phone', '').strip() or s.emergency_contact_phone
        s.shirt_size = request.form.get('shirt_size', '').strip()
        s.payment_pref = request.form.get('payment_pref', '').strip()
        s.payment_notes = request.form.get('payment_notes', '').strip()
        s.welcome_forms_at = datetime.utcnow()
        # Auto-complete three onboarding steps at once
        steps = s.get_onboarding()
        for step in ('welcome_forms', 'payment_info', 'uniform_size'):
            if step not in steps:
                steps.append(step)
        s.onboarding_steps = json.dumps(steps)
        db.session.commit()

        # Notify owner that forms are done
        import os
        owner_email = BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL', '')
        if owner_email:
            send_email(
                to_email=owner_email, to_name=biz,
                from_name=f'{biz} Onboarding',
                subject=f'{s.name} completed their onboarding forms — {biz}',
                html=f"""<div style="font-family:Inter,sans-serif;max-width:500px;margin:0 auto;color:#1f1333">
  <h3 style="color:#b98a33">Onboarding Forms Received</h3>
  <p><strong>{s.name}</strong> just completed their onboarding forms.</p>
  <p><strong>Shirt size:</strong> {s.shirt_size or '—'}</p>
  <p><strong>Payment preference:</strong> {s.payment_pref or '—'}</p>
  <p><strong>Payment notes:</strong> {s.payment_notes or '—'}</p>
  <p><strong>Emergency contact:</strong> {s.emergency_contact_name or '—'} — {s.emergency_contact_phone or '—'}</p>
  <p>Log in to the CRM to continue their onboarding.</p>
</div>""",
            )
        return render_template('public/onboarding_forms_done.html', s=s, biz=biz, already_done=False)

    return render_template('public/onboarding_forms.html', s=s, biz=biz)


# ── Orientation completion (public) ────────────────────────────────────────────

@contractors_bp.route('/orientation-complete/<token>', methods=['GET', 'POST'])
def orientation_complete(token):
    s = Staff.query.filter_by(orientation_token=token).first_or_404()
    biz = BusinessSetting.get('business_name') or 'Dazzle & Shine Maids'
    already_done = bool(s.orientation_completed_at)

    if request.method == 'POST':
        if already_done:
            # Already done — just show the materials again (review mode), no re-submit needed
            return render_template('public/orientation_done.html', s=s, biz=biz,
                                   already_done=True, confirm_mode=False)
        s.orientation_completed_at = datetime.utcnow()
        steps = s.get_onboarding()
        if 'orientation' not in steps:
            steps.append('orientation')
            s.onboarding_steps = json.dumps(steps)
        db.session.commit()

        import os
        owner_email = BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL', '')
        if owner_email:
            send_email(
                to_email=owner_email, to_name=biz,
                from_name=f'{biz} Onboarding',
                subject=f'{s.name} completed orientation — ready to schedule! — {biz}',
                html=f"""<div style="font-family:Inter,sans-serif;max-width:500px;margin:0 auto;color:#1f1333">
  <h3 style="color:#b98a33">Orientation Complete!</h3>
  <p><strong>{s.name}</strong> has confirmed they completed their orientation and training.</p>
  <p>They are ready to be scheduled for their first job. Log in to the CRM to assign them.</p>
</div>""",
            )
        return render_template('public/orientation_done.html', s=s, biz=biz,
                               already_done=False, confirm_mode=False)

    # GET — always show training materials; already_done disables the submit button
    return render_template('public/orientation_done.html', s=s, biz=biz,
                           already_done=already_done, confirm_mode=True)


@contractors_bp.route('/team/<int:staff_id>/reset-orientation', methods=['POST'])
@login_required
def reset_orientation(staff_id):
    s = Staff.query.get_or_404(staff_id)
    s.orientation_completed_at = None
    steps = s.get_onboarding()
    if 'orientation' in steps:
        steps.remove('orientation')
        s.onboarding_steps = json.dumps(steps)
    db.session.commit()
    flash(f'Orientation reset for {s.name} — they can re-complete training via their link.', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=staff_id))


def _send_auto_rejection(app_rec, reasons_en, reasons_es):
    biz = 'Dazzle & Shine Maids'
    reasons_html_en = ''.join(f'<li style="margin-bottom:6px">{r}</li>' for r in reasons_en)
    reasons_html_es = ''.join(f'<li style="margin-bottom:6px">{r}</li>' for r in reasons_es)
    html = f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;background:#f6f5fb">
  <div style="background:#1f1333;padding:24px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;font-family:Georgia,serif;margin:0;font-size:1.6rem">Dazzle &amp; Shine Maids</h1>
  </div>
  <div style="padding:28px 32px;background:#fff;border-left:4px solid #d3a84f">
    <p style="font-size:0.72rem;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;color:#d3a84f;margin:0 0 14px">🇺🇸 English</p>
    <h2 style="color:#1f1333;margin:0 0 12px">Hi {app_rec.name},</h2>
    <p style="color:#3b2b6b;line-height:1.7">
      Thank you for your interest in joining <strong>{biz}</strong>. We reviewed your application
      and unfortunately we are unable to move forward at this time for the following reason(s):
    </p>
    <ul style="color:#3b2b6b;line-height:1.8;margin:14px 0;padding-left:20px">
      {reasons_html_en}
    </ul>
    <p style="color:#3b2b6b;line-height:1.7">
      We appreciate you taking the time to apply and wish you all the best in your job search.
    </p>
    <p style="color:#3b2b6b">Warm regards,<br><strong>The {biz} Team</strong></p>
  </div>
  <div style="padding:12px 32px;background:#f6f5fb;text-align:center">
    <div style="border-top:2px dashed #e4dfef"></div>
  </div>
  <div style="padding:28px 32px;background:#fff;border-left:4px solid #5d4f7d">
    <p style="font-size:0.72rem;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;color:#5d4f7d;margin:0 0 14px">🇪🇸 Español</p>
    <h2 style="color:#1f1333;margin:0 0 12px">Hola {app_rec.name},</h2>
    <p style="color:#3b2b6b;line-height:1.7">
      Gracias por tu interés en unirte a <strong>{biz}</strong>. Revisamos tu solicitud
      y lamentablemente no podemos continuar en este momento por la(s) siguiente(s) razón(es):
    </p>
    <ul style="color:#3b2b6b;line-height:1.8;margin:14px 0;padding-left:20px">
      {reasons_html_es}
    </ul>
    <p style="color:#3b2b6b;line-height:1.7">
      Apreciamos el tiempo que tomaste para aplicar y te deseamos lo mejor en tu búsqueda de empleo.
    </p>
    <p style="color:#3b2b6b">Saludos,<br><strong>El equipo de {biz}</strong></p>
  </div>
  <div style="padding:14px 32px;background:#1f1333;border-radius:0 0 12px 12px;text-align:center">
    <p style="color:rgba(255,255,255,0.4);font-size:0.78rem;margin:0">{biz} · Questions? Reply to this email.</p>
  </div>
</div>"""
    send_email(
        to_email=app_rec.email,
        to_name=app_rec.name,
        subject=f"Your Application to {biz}",
        html=html,
    )


def _delayed_send_invite(flask_app, application_id):
    """Runs in a background thread after a 10-minute delay."""
    with flask_app.app_context():
        from models import ContractorApplication
        from extensions import db
        from blueprints.interviews import send_interview_invite_email
        app_rec = ContractorApplication.query.get(application_id)
        if not app_rec or app_rec.interview_status != 'pending':
            return
        if not app_rec.interview_token:
            app_rec.interview_token = secrets.token_urlsafe(32)
        app_rec.interview_status = 'sent'
        app_rec.interview_sent_at = datetime.utcnow()
        db.session.commit()
        try:
            send_interview_invite_email(app_rec)
        except Exception:
            pass


def _default_agreement(biz_name, worker_model):
    if worker_model == 'employee':
        return f"""OFFER OF EMPLOYMENT — {biz_name.upper()}

This letter confirms your offer of employment with {biz_name} ("the Company").

POSITION & DUTIES
You are being hired as a Cleaning Technician. Your duties include performing residential and/or commercial cleaning services as assigned, following all company standards, checklists, and quality guidelines.

COMPENSATION
Your pay rate will be provided separately by your manager. Pay periods are [weekly/bi-weekly]. Direct deposit is available.

SCHEDULE
Your schedule will be assigned by {biz_name} management. Availability requirements were discussed during your interview.

CONDUCT & STANDARDS
You are expected to maintain professional conduct at all times, treat clients and their property with care and respect, and follow all company policies, safety procedures, and quality checklists.

CONFIDENTIALITY
You agree to keep all client information, business processes, and pricing confidential during and after your employment.

AT-WILL EMPLOYMENT
Employment with {biz_name} is at-will. Either party may end the employment relationship at any time with or without cause or notice.

ACKNOWLEDGMENT
By signing below, you confirm that you have read and understood this agreement and agree to its terms."""
    else:
        return f"""INDEPENDENT CONTRACTOR AGREEMENT — {biz_name.upper()}

This Independent Contractor Agreement ("Agreement") is entered into between {biz_name} ("Company") and the Contractor identified below.

1. INDEPENDENT CONTRACTOR STATUS
You are engaged as an independent contractor, not an employee. You are responsible for your own taxes, insurance, and equipment unless otherwise agreed. You will receive a 1099 form at year-end if applicable.

2. SERVICES
You agree to provide residential and/or commercial cleaning services as assigned by {biz_name}, following all company quality standards, checklists, and client expectations.

3. COMPENSATION
Your pay rate (percentage of job or hourly) was communicated during onboarding. Payment is issued [weekly/bi-weekly] after jobs are marked complete.

4. SCHEDULING
Jobs will be offered to you based on availability. You may accept or decline jobs, but consistent availability is expected. Last-minute cancellations must be communicated immediately.

5. CONDUCT & QUALITY
You agree to: arrive on time, maintain professional appearance and communication, follow all cleaning checklists, treat client homes and belongings with the utmost care, and never solicit clients directly.

6. CONFIDENTIALITY & NON-SOLICITATION
You agree to keep all client information, pricing, and business processes strictly confidential. For 12 months after this agreement ends, you agree not to solicit or accept direct business from any {biz_name} client.

7. TERMINATION
Either party may terminate this agreement at any time with or without cause.

ACKNOWLEDGMENT
By signing below, you confirm that you have read and understood this Agreement and agree to its terms as an independent contractor."""
