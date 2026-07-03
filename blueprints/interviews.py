import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, abort, url_for, flash, redirect
from auth import login_required
from models import ContractorApplication, InterviewResponse
from extensions import db
from notifications import send_email

interviews_bp = Blueprint('interviews', __name__)


def send_interview_invite_email(app_rec):
    """Send the bilingual interview + background check invitation email.
    Can be called from the admin manual route OR the auto-filter delayed timer."""
    biz = 'Dazzle & Shine Maids'
    interview_url = url_for('interviews.interview_page',
                            token=app_rec.interview_token, _external=True)
    html = _build_invite_html(app_rec.name, interview_url, biz)
    send_email(
        to_email=app_rec.email,
        to_name=app_rec.name,
        subject=f"Next Steps: Video Interview + Background Check — {biz}",
        html=html,
    )

QUESTIONS_EN = [
    "Tell me about your cleaning experience.",
    "Are you comfortable working independently without supervision?",
    "Do you have reliable transportation?",
    "Are you available on weekends?",
    "Why do you want to work with Dazzle & Shine?",
]

QUESTIONS_ES = [
    "Cuéntame sobre tu experiencia en limpieza.",
    "¿Te sientes cómodo/a trabajando de forma independiente sin supervisión?",
    "¿Tienes transporte propio y confiable?",
    "¿Estás disponible los fines de semana?",
    "¿Por qué quieres trabajar con Dazzle & Shine?",
]


# ── Public (no login) ──────────────────────────────────────────────────────────

@interviews_bp.route('/interview/<token>')
def interview_page(token):
    app_rec = ContractorApplication.query.filter_by(interview_token=token).first_or_404()
    if app_rec.interview_status == 'completed':
        return render_template('interview/complete.html', app=app_rec, already_done=True)

    if app_rec.interview_status == 'sent':
        app_rec.interview_status = 'in_progress'
        db.session.commit()

    answered = [r.question_index for r in app_rec.responses]
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', 'dasgvqtyk')
    upload_preset = os.environ.get('CLOUDINARY_UPLOAD_PRESET', 'dazzle_interviews')

    return render_template('interview/interview.html',
        app=app_rec,
        questions_en=QUESTIONS_EN,
        questions_es=QUESTIONS_ES,
        answered=answered,
        cloud_name=cloud_name,
        upload_preset=upload_preset,
    )


@interviews_bp.route('/interview/<token>/save', methods=['POST'])
def save_response(token):
    app_rec = ContractorApplication.query.filter_by(interview_token=token).first_or_404()
    data = request.get_json() or {}

    q_index = data.get('question_index')
    public_id = data.get('cloudinary_public_id', '').strip()
    url = data.get('cloudinary_url', '').strip()
    question_en = data.get('question_en', '')
    transcript = data.get('transcript', '').strip()
    transcript_lang = data.get('transcript_lang', 'en')

    if q_index is None or not public_id or not url:
        return jsonify({'error': 'Missing fields'}), 400

    existing = InterviewResponse.query.filter_by(
        application_id=app_rec.id, question_index=q_index
    ).first()

    if existing:
        existing.cloudinary_public_id = public_id
        existing.cloudinary_url = url
        existing.question_en = question_en
        existing.transcript = transcript or existing.transcript
        existing.transcript_lang = transcript_lang
    else:
        db.session.add(InterviewResponse(
            application_id=app_rec.id,
            question_index=q_index,
            question_en=question_en,
            cloudinary_public_id=public_id,
            cloudinary_url=url,
            transcript=transcript,
            transcript_lang=transcript_lang,
        ))

    db.session.commit()
    return jsonify({'ok': True})


@interviews_bp.route('/interview/<token>/complete', methods=['POST'])
def complete_interview(token):
    app_rec = ContractorApplication.query.filter_by(interview_token=token).first_or_404()
    app_rec.interview_status = 'completed'
    app_rec.interview_completed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})


# ── Background check upload (public, token-gated) ────────────────────────────────

@interviews_bp.route('/background-check/<token>')
def bgcheck_upload_page(token):
    app_rec = ContractorApplication.query.filter_by(bgcheck_upload_token=token).first_or_404()
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', 'dasgvqtyk')
    upload_preset = os.environ.get('CLOUDINARY_UPLOAD_PRESET', 'dazzle_interviews')
    already_done = bool(app_rec.bgcheck_uploaded_at)
    return render_template('interview/bgcheck_upload.html',
        app=app_rec,
        token=token,
        cloud_name=cloud_name,
        upload_preset=upload_preset,
        already_done=already_done,
    )


@interviews_bp.route('/background-check/<token>/submit', methods=['POST'])
def bgcheck_submit(token):
    app_rec = ContractorApplication.query.filter_by(bgcheck_upload_token=token).first_or_404()
    data = request.get_json() or {}

    uploaded_url = (data.get('uploaded_url') or '').strip()
    verification_link = (data.get('verification_link') or '').strip()

    if not uploaded_url and not verification_link:
        return jsonify({'error': 'Please upload a file or paste a link.'}), 400

    if uploaded_url:
        app_rec.bgcheck_uploaded_url = uploaded_url
    if verification_link:
        app_rec.bgcheck_uploaded_link = verification_link
    app_rec.bgcheck_uploaded_at = datetime.utcnow()
    app_rec.bgcheck_results_received = True
    app_rec.background_check_status = 'received'
    db.session.commit()

    # Notify the owner
    biz = 'Dazzle & Shine Maids'
    owner_email = os.environ.get('OWNER_EMAIL', 'dazzleandshinemaids@gmail.com')
    try:
        send_email(
            to_email=owner_email,
            to_name=biz,
            subject=f"Background check submitted — {app_rec.name}",
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <h2 style="color:#1f1333">{app_rec.name} submitted their background check</h2>
  <p style="color:#3b2b6b">Review it in the CRM and mark them Cleared or Failed.</p>
  <p style="color:#3b2b6b"><a href="{url_for('contractors.application_detail', app_id=app_rec.id, _external=True)}"
     style="color:#d3a84f;font-weight:700">Open {app_rec.name}'s application →</a></p>
</div>""",
        )
    except Exception:
        pass

    return jsonify({'ok': True})


# ── Admin (login required) ──────────────────────────────────────────────────────

@interviews_bp.route('/admin/interviews')
@login_required
def admin_interviews():
    status_filter = request.args.get('status', '')
    q = ContractorApplication.query.filter(
        ContractorApplication.interview_status.isnot(None),
        ContractorApplication.interview_status != 'not_sent',
    ).order_by(ContractorApplication.interview_sent_at.desc())

    if status_filter:
        q = q.filter_by(interview_status=status_filter)

    apps = q.all()
    counts = {s: ContractorApplication.query.filter_by(interview_status=s).count()
              for s in ('sent', 'in_progress', 'completed')}
    counts['all'] = sum(counts.values())

    return render_template('admin/interviews.html',
        apps=apps, counts=counts, status_filter=status_filter)


@interviews_bp.route('/admin/interviews/<int:app_id>')
@login_required
def review_interview(app_id):
    app_rec = ContractorApplication.query.get_or_404(app_id)
    responses = InterviewResponse.query.filter_by(application_id=app_id)\
        .order_by(InterviewResponse.question_index).all()
    return render_template('admin/interview_review.html',
        app=app_rec, responses=responses, questions_en=QUESTIONS_EN)


@interviews_bp.route('/admin/interviews/<int:app_id>/approve', methods=['POST'])
@login_required
def approve_interview(app_id):
    app_rec = ContractorApplication.query.get_or_404(app_id)
    app_rec.status = 'reviewing'
    app_rec.background_check_status = 'requested'
    app_rec.bgcheck_request_sent_at = datetime.utcnow()
    app_rec.offer_sent_at = datetime.utcnow()
    app_rec.offer_sent_count = (app_rec.offer_sent_count or 0) + 1
    if not app_rec.bgcheck_upload_token:
        app_rec.bgcheck_upload_token = secrets.token_urlsafe(32)
    db.session.commit()

    # Send candidate a focused background check reminder
    biz = 'Dazzle & Shine Maids'
    upload_url = url_for('interviews.bgcheck_upload_page',
                         token=app_rec.bgcheck_upload_token, _external=True)
    send_email(
        to_email=app_rec.email,
        to_name=app_rec.name,
        subject=f"Welcome to the Team (Pending Your Background Check) — {biz}",
        html=_build_bgcheck_email(app_rec.name, biz, upload_url),
    )

    flash(f'Video approved! Conditional offer + background check link sent to {app_rec.name}.', 'success')
    return redirect(url_for('contractors.application_detail', app_id=app_rec.id))


@interviews_bp.route('/admin/interviews/<int:app_id>/resend-offer', methods=['POST'])
@login_required
def resend_offer(app_id):
    """Re-send the conditional offer / background-check email at any stage —
    e.g. for candidates approved before the conditional-offer email existed."""
    app_rec = ContractorApplication.query.get_or_404(app_id)
    if not app_rec.bgcheck_upload_token:
        app_rec.bgcheck_upload_token = secrets.token_urlsafe(32)
    # Make sure they're flagged as awaiting a background check
    if app_rec.status not in ('hired', 'onboarding', 'rejected'):
        app_rec.status = 'reviewing'
    if app_rec.background_check_status in (None, '', 'not_started'):
        app_rec.background_check_status = 'requested'
        app_rec.bgcheck_request_sent_at = datetime.utcnow()
    app_rec.offer_sent_at = datetime.utcnow()
    app_rec.offer_sent_count = (app_rec.offer_sent_count or 0) + 1
    db.session.commit()

    biz = 'Dazzle & Shine Maids'
    upload_url = url_for('interviews.bgcheck_upload_page',
                         token=app_rec.bgcheck_upload_token, _external=True)
    send_email(
        to_email=app_rec.email, to_name=app_rec.name,
        subject=f"Welcome to the Team (Pending Your Background Check) — {biz}",
        html=_build_bgcheck_email(app_rec.name, biz, upload_url),
    )
    flash(f'Conditional offer email sent to {app_rec.name}.', 'success')
    return redirect(request.referrer or url_for('contractors.application_detail', app_id=app_rec.id))


@interviews_bp.route('/admin/interviews/<int:app_id>/reject', methods=['POST'])
@login_required
def reject_interview(app_id):
    app_rec = ContractorApplication.query.get_or_404(app_id)
    app_rec.status = 'rejected'
    db.session.commit()

    biz = 'Dazzle & Shine Maids'
    html = f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:32px;background:#f6f5fb">
  <div style="background:#1f1333;padding:24px;border-radius:12px;text-align:center;margin-bottom:24px">
    <h1 style="color:#d3a84f;font-family:Georgia,serif;margin:0">Dazzle &amp; Shine Maids</h1>
  </div>
  <h2 style="color:#1f1333">Hi {app_rec.name},</h2>
  <p style="color:#3b2b6b">Thank you so much for taking the time to apply and complete your video interview with {biz}.</p>
  <p style="color:#3b2b6b">After careful consideration, we've decided to move forward with other candidates at this time.
     We truly appreciate your interest and the effort you put into your application.</p>
  <p style="color:#3b2b6b">We wish you all the best — keep shining!</p>
  <p style="color:#3b2b6b">Warm regards,<br><strong>The {biz} Team</strong></p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:24px 0">
  <p style="color:#9a95ad;font-size:0.8rem">{biz} · Questions? Reply to this email.</p>
</div>"""

    send_email(
        to_email=app_rec.email,
        to_name=app_rec.name,
        subject=f"Update on Your Application — {biz}",
        html=html,
    )

    flash(f'{app_rec.name} rejected. Polite email sent.', 'info')
    return redirect(url_for('contractors.application_detail', app_id=app_rec.id))


@interviews_bp.route('/admin/interviews/send/<int:app_id>', methods=['POST'])
@login_required
def send_invite(app_id):
    app_rec = ContractorApplication.query.get_or_404(app_id)

    if not app_rec.interview_token:
        app_rec.interview_token = secrets.token_urlsafe(32)

    _now = datetime.utcnow()
    app_rec.interview_status = 'sent'
    app_rec.interview_sent_at = _now
    app_rec.interview_last_sent_at = _now
    app_rec.interview_nudge_count = 0   # manual re-send restarts the follow-up clock
    db.session.commit()

    send_interview_invite_email(app_rec)

    flash(f'Interview link sent to {app_rec.name} at {app_rec.email}', 'success')
    return redirect(request.referrer or url_for('interviews.admin_interviews'))


def _build_bgcheck_email(name, biz, upload_url='#'):
    first = (name or 'there').split()[0]
    return f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;background:#f6f5fb">
  <div style="background:#1f1333;padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;font-family:Georgia,serif;margin:0 0 6px;font-size:1.8rem">Dazzle &amp; Shine Maids</h1>
    <p style="color:rgba(255,255,255,0.6);margin:0;font-size:0.85rem;letter-spacing:0.1em;text-transform:uppercase">
      Welcome to the Team — Pending Your Background Check
    </p>
  </div>

  <!-- ENGLISH -->
  <div style="padding:32px;background:#fff;border-left:4px solid #d3a84f">
    <h2 style="color:#1f1333;margin:0 0 12px">Congratulations, {first}! 🎉</h2>
    <p style="color:#3b2b6b;line-height:1.8;margin:0 0 16px">
      We loved your video interview, and <strong>we'd love to bring you onto the Dazzle &amp; Shine Maids team
      as an independent contractor</strong> — contingent on a clear background check.
      Consider this your official welcome (almost)!
    </p>

    <div style="background:#f6f5fb;border-left:3px solid #d3a84f;border-radius:6px;padding:14px 18px;margin:0 0 22px">
      <p style="color:#5f5878;line-height:1.7;margin:0;font-style:italic">
        A personal note from me: I started Dazzle &amp; Shine to build a team of people who take pride in their
        work and treat every client's home like their own. I'm genuinely excited about the care you'll bring
        to our clients. — Monica, Owner
      </p>
    </div>

    <!-- PAY -->
    <div style="background:#f0fff7;border:1px solid #a3cfbb;border-radius:10px;padding:20px 22px;margin:0 0 20px">
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:10px">💵 What You'll Earn</div>
      <p style="color:#1e5638;line-height:1.7;margin:0 0 12px">
        You start at <strong>50% of every job</strong> you complete, paid after each clean. In real terms,
        that's about <strong>$35–$48 an hour</strong> depending on the home. For example:
      </p>
      <ul style="color:#1e5638;line-height:1.9;margin:0 0 6px;padding-left:20px">
        <li>A 1-bed/1-bath standard clean is a $145 job — <strong>you earn $72.50</strong> for about 1.5 hours (~$48/hr).</li>
        <li>A 3-bed/2-bath standard clean is a $225 job — <strong>you earn $112.50</strong> for about 3 hours (~$37/hr).</li>
      </ul>
      <p style="color:#1e7e34;font-size:0.9rem;margin:10px 0 0;font-weight:600">⭐ Our top performers grow to 55% of every job — earn it with great reviews and reliability.</p>
      <p style="color:#1e7e34;font-size:0.85rem;margin:6px 0 0">The more efficiently you work, the higher your effective hourly rate.</p>
    </div>

    <!-- IC EXPECTATIONS -->
    <div style="background:#fff8e1;border:1px solid #f0d488;border-radius:10px;padding:20px 22px;margin:0 0 20px">
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:10px">📋 What to Know as an Independent Contractor</div>
      <ul style="color:#7c4a04;line-height:1.9;margin:0;padding-left:20px">
        <li>You provide your <strong>own cleaning supplies and equipment</strong>.</li>
        <li><strong>No uniform is provided</strong> — please wear neat, professional attire.</li>
        <li>You use your <strong>own reliable transportation</strong>.</li>
        <li>You're responsible for your <strong>own taxes and insurance</strong> (you'll receive a 1099).</li>
        <li>You choose your schedule by accepting the jobs that work for you.</li>
      </ul>
    </div>

    <!-- BACKGROUND CHECK -->
    <div style="background:#fef9ec;border:2px solid #d3a84f;border-radius:10px;padding:22px 24px;margin-bottom:22px">
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:10px">🔍 Your One Remaining Step — Background Check</div>
      <p style="color:#7c4a04;line-height:1.7;margin:0 0 12px">
        Your offer is contingent on a clear background check, at your own cost (typically $20–$40).
        Use <a href="https://checkr.com" style="color:#d3a84f;font-weight:600">Checkr.com</a>, or submit a recent
        Care.com check if you already have one. Please complete it within <strong>7 days</strong> and upload your results below.
      </p>
      <div style="text-align:center;margin-top:14px">
        <a href="{upload_url}"
           style="background:#1f1333;color:#d3a84f;padding:14px 32px;border-radius:8px;
                  text-decoration:none;font-weight:700;font-size:1rem;display:inline-block">
          📎 Submit My Background Check →
        </a>
      </div>
      <p style="color:#9a95ad;font-size:0.8rem;margin:12px 0 0;line-height:1.5;text-align:center">
        Just upload a PDF or a clear screenshot of your results.
      </p>
    </div>

    <!-- NEXT STEPS -->
    <div style="margin-bottom:8px">
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:6px">✅ What Happens Next</div>
      <p style="color:#3b2b6b;line-height:1.7;margin:0">
        Once your check clears, we'll send your contractor agreement to sign and schedule your first job. Welcome aboard!
      </p>
    </div>

    <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0">
    <p style="color:#5f5878;font-size:0.82rem;line-height:1.6;margin:0">
      Questions? Just reply to this email. We can't wait to welcome you to the Dazzle &amp; Shine family!
    </p>
  </div>

  <!-- ESPAÑOL -->
  <div style="padding:32px;background:#fff;border-left:4px solid #5d4f7d;border-top:2px dashed #e4dfef">
    <h2 style="color:#1f1333;margin:0 0 12px">¡Felicidades, {first}! 🎉</h2>
    <p style="color:#3b2b6b;line-height:1.8;margin:0 0 16px">
      ¡Nos encantó tu entrevista en video y <strong>nos encantaría sumarte al equipo de Dazzle &amp; Shine Maids
      como contratista independiente</strong> — sujeto a una verificación de antecedentes sin problemas!
      Considera esta tu bienvenida oficial (casi).
    </p>

    <div style="background:#f6f5fb;border-left:3px solid #5d4f7d;border-radius:6px;padding:14px 18px;margin:0 0 22px">
      <p style="color:#5f5878;line-height:1.7;margin:0;font-style:italic">
        Una nota personal de mi parte: Fundé Dazzle &amp; Shine para formar un equipo de personas que se enorgullecen
        de su trabajo y tratan cada hogar como si fuera el suyo. Estoy muy emocionada por el cuidado que les brindarás
        a nuestros clientes. — Monica, Propietaria
      </p>
    </div>

    <!-- PAGO -->
    <div style="background:#f0fff7;border:1px solid #a3cfbb;border-radius:10px;padding:20px 22px;margin:0 0 20px">
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:10px">💵 Lo que Ganarás</div>
      <p style="color:#1e5638;line-height:1.7;margin:0 0 12px">
        Comienzas con el <strong>50% de cada trabajo</strong> que completes, pagado después de cada limpieza. En términos reales,
        eso es aproximadamente <strong>$35–$48 por hora</strong> según el hogar. Por ejemplo:
      </p>
      <ul style="color:#1e5638;line-height:1.9;margin:0 0 6px;padding-left:20px">
        <li>Una limpieza estándar de 1 hab/1 baño es un trabajo de $145 — <strong>ganas $72.50</strong> por aprox. 1.5 horas (~$48/hr).</li>
        <li>Una limpieza estándar de 3 hab/2 baños es un trabajo de $225 — <strong>ganas $112.50</strong> por aprox. 3 horas (~$37/hr).</li>
      </ul>
      <p style="color:#1e7e34;font-size:0.9rem;margin:10px 0 0;font-weight:600">⭐ Nuestros mejores contratistas crecen al 55% de cada trabajo — gánalo con excelentes reseñas y confiabilidad.</p>
      <p style="color:#1e7e34;font-size:0.85rem;margin:6px 0 0">Cuanto más eficiente trabajes, mayor será tu tarifa por hora.</p>
    </div>

    <!-- EXPECTATIVAS IC -->
    <div style="background:#fff8e1;border:1px solid #f0d488;border-radius:10px;padding:20px 22px;margin:0 0 20px">
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:10px">📋 Lo que Debes Saber como Contratista Independiente</div>
      <ul style="color:#7c4a04;line-height:1.9;margin:0;padding-left:20px">
        <li>Tú aportas tus <strong>propios materiales y equipos de limpieza</strong>.</li>
        <li><strong>No se proporciona uniforme</strong> — por favor usa vestimenta limpia y profesional.</li>
        <li>Usas tu <strong>propio transporte confiable</strong>.</li>
        <li>Eres responsable de tus <strong>propios impuestos y seguro</strong> (recibirás un 1099).</li>
        <li>Eliges tu horario aceptando los trabajos que te convengan.</li>
      </ul>
    </div>

    <!-- VERIFICACIÓN -->
    <div style="background:#fef9ec;border:2px solid #5d4f7d;border-radius:10px;padding:22px 24px;margin-bottom:22px">
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:10px">🔍 Tu Único Paso Restante — Verificación de Antecedentes</div>
      <p style="color:#7c4a04;line-height:1.7;margin:0 0 12px">
        Tu oferta está sujeta a una verificación de antecedentes sin problemas, por tu cuenta (generalmente $20–$40).
        Usa <a href="https://checkr.com" style="color:#d3a84f;font-weight:600">Checkr.com</a>, o envía una verificación
        reciente de Care.com si ya la tienes. Complétala dentro de <strong>7 días</strong> y sube tus resultados abajo.
      </p>
      <div style="text-align:center;margin-top:14px">
        <a href="{upload_url}"
           style="background:#1f1333;color:#d3a84f;padding:14px 32px;border-radius:8px;
                  text-decoration:none;font-weight:700;font-size:1rem;display:inline-block">
          📎 Enviar mi Verificación de Antecedentes →
        </a>
      </div>
      <p style="color:#9a95ad;font-size:0.8rem;margin:12px 0 0;line-height:1.5;text-align:center">
        Solo sube un PDF o una captura de pantalla clara de tus resultados.
      </p>
    </div>

    <!-- SIGUIENTE -->
    <div>
      <div style="font-weight:700;color:#1f1333;font-size:1.05rem;margin-bottom:6px">✅ Qué Sigue</div>
      <p style="color:#3b2b6b;line-height:1.7;margin:0">
        Una vez que tu verificación esté lista, te enviaremos tu acuerdo de contratista para firmar y programaremos
        tu primer trabajo. ¡Bienvenido/a al equipo!
      </p>
    </div>
  </div>

  <div style="padding:16px 32px;background:#1f1333;border-radius:0 0 12px 12px;text-align:center">
    <p style="color:rgba(255,255,255,0.4);font-size:0.78rem;margin:0">{biz} · Questions? Reply to this email.</p>
  </div>
</div>"""


def _build_invite_html(name, interview_url, biz):
    return f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;background:#f6f5fb">

  <!-- HEADER -->
  <div style="background:#1f1333;padding:28px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;font-family:Georgia,serif;margin:0 0 6px;font-size:1.8rem">
      Dazzle &amp; Shine Maids
    </h1>
    <p style="color:rgba(255,255,255,0.6);margin:0;font-size:0.85rem;letter-spacing:0.1em;
              text-transform:uppercase">
      Next Steps: Video Interview &amp; Background Check
    </p>
  </div>

  <!-- ENGLISH SECTION -->
  <div style="padding:32px;background:#ffffff;border-left:4px solid #d3a84f">
    <p style="font-size:0.72rem;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;
              color:#d3a84f;margin:0 0 14px">🇺🇸 English</p>

    <h2 style="color:#1f1333;margin:0 0 12px">Hi {name}!</h2>
    <p style="color:#3b2b6b;line-height:1.8;margin:0 0 12px">
      Congratulations — you've been selected to move forward with <strong>Dazzle &amp; Shine Maids</strong>!
      Please complete <strong>both steps below</strong> to continue your application.
    </p>

    <!-- STEP 1 -->
    <div style="background:#f6f5fb;border-radius:10px;padding:18px 20px;margin:20px 0">
      <div style="font-weight:700;color:#1f1333;font-size:1rem;margin-bottom:8px">
        ✅ Step 1 — Complete Your Video Interview
      </div>
      <p style="color:#3b2b6b;line-height:1.7;margin:0 0 10px">
        Click the button below to answer 5 short questions on camera. No app download needed —
        it works right in your browser on your phone or computer.
        <strong>Takes about 5–10 minutes.</strong>
      </p>
      <ul style="color:#3b2b6b;line-height:2;margin:0;padding-left:20px">
        <li>Allow camera &amp; microphone access when prompted</li>
        <li>Read each question and record your answer</li>
        <li>A <strong>Spanish language option</strong> is available on the interview page (top right corner)</li>
        <li>Submit each answer before moving to the next question</li>
      </ul>
    </div>

    <div style="text-align:center;margin:24px 0">
      <a href="{interview_url}"
         style="background:#d3a84f;color:#1f1333;padding:15px 36px;border-radius:8px;
                text-decoration:none;font-weight:700;font-size:1.05rem;display:inline-block">
        Start My Video Interview →
      </a>
    </div>

    <!-- STEP 2 -->
    <div style="background:#f6f5fb;border-radius:10px;padding:18px 20px;margin:20px 0">
      <div style="font-weight:700;color:#1f1333;font-size:1rem;margin-bottom:8px">
        🔍 Step 2 — Complete a Background Check
      </div>
      <p style="color:#3b2b6b;line-height:1.7;margin:0 0 12px">
        A background check is <strong>required</strong> for all contractors. This is at your own cost.
        You have two options:
      </p>
      <div style="margin-bottom:10px;padding:12px 14px;background:#fff;border-radius:8px;
                  border:1px solid #e4dfef">
        <strong style="color:#1f1333">Option A — Checkr.com</strong><br>
        <span style="color:#3b2b6b;font-size:0.9rem">
          Visit <a href="https://checkr.com" style="color:#d3a84f">checkr.com</a> to order your own
          background check report. Once complete, email us the results.
        </span>
      </div>
      <div style="padding:12px 14px;background:#fff;border-radius:8px;border:1px solid #e4dfef">
        <strong style="color:#1f1333">Option B — Care.com Background Check</strong><br>
        <span style="color:#3b2b6b;font-size:0.9rem">
          If you already have a background check on file from Care.com, you may upload or
          forward that to us and we will accept it.
        </span>
      </div>
      <p style="color:#5f5878;font-size:0.85rem;margin:12px 0 0;line-height:1.6">
        Please complete your background check within <strong>7 days</strong> of receiving this email.
        Email your results to
        <a href="mailto:dazzleandshinemaids@gmail.com" style="color:#d3a84f">
          dazzleandshinemaids@gmail.com
        </a>
      </p>
    </div>

    <p style="color:#9a95ad;font-size:0.82rem;line-height:1.6;margin:16px 0 0">
      Your interview link is unique to you — please don't share it. Questions? Reply to this email.
    </p>
  </div>

  <!-- DIVIDER -->
  <div style="padding:12px 32px;background:#f6f5fb;text-align:center">
    <div style="border-top:2px dashed #e4dfef"></div>
  </div>

  <!-- SPANISH SECTION -->
  <div style="padding:32px;background:#ffffff;border-left:4px solid #5d4f7d">
    <p style="font-size:0.72rem;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;
              color:#5d4f7d;margin:0 0 14px">🇪🇸 Español</p>

    <h2 style="color:#1f1333;margin:0 0 12px">¡Hola {name}!</h2>
    <p style="color:#3b2b6b;line-height:1.8;margin:0 0 12px">
      ¡Felicitaciones! Has sido seleccionado/a para avanzar con <strong>Dazzle &amp; Shine Maids</strong>.
      Por favor completa <strong>los dos pasos a continuación</strong> para continuar tu solicitud.
    </p>

    <!-- PASO 1 -->
    <div style="background:#f6f5fb;border-radius:10px;padding:18px 20px;margin:20px 0">
      <div style="font-weight:700;color:#1f1333;font-size:1rem;margin-bottom:8px">
        ✅ Paso 1 — Completa tu Entrevista en Video
      </div>
      <p style="color:#3b2b6b;line-height:1.7;margin:0 0 10px">
        Haz clic en el botón de arriba para responder 5 preguntas cortas en cámara.
        No necesitas descargar ninguna aplicación — funciona directamente en tu teléfono o computadora.
        <strong>Toma entre 5 y 10 minutos.</strong>
      </p>
      <ul style="color:#3b2b6b;line-height:2;margin:0;padding-left:20px">
        <li>Permite el acceso a la cámara y micrófono cuando se te solicite</li>
        <li>Lee cada pregunta y graba tu respuesta</li>
        <li>Hay una <strong>opción en español</strong> disponible en la página de la entrevista (esquina superior derecha)</li>
        <li>Envía cada respuesta antes de pasar a la siguiente pregunta</li>
      </ul>
    </div>

    <!-- PASO 2 -->
    <div style="background:#f6f5fb;border-radius:10px;padding:18px 20px;margin:20px 0">
      <div style="font-weight:700;color:#1f1333;font-size:1rem;margin-bottom:8px">
        🔍 Paso 2 — Verificación de Antecedentes
      </div>
      <p style="color:#3b2b6b;line-height:1.7;margin:0 0 12px">
        Una verificación de antecedentes es <strong>obligatoria</strong> para todos los contratistas.
        Este costo corre por tu cuenta. Tienes dos opciones:
      </p>
      <div style="margin-bottom:10px;padding:12px 14px;background:#fff;border-radius:8px;
                  border:1px solid #e4dfef">
        <strong style="color:#1f1333">Opción A — Checkr.com</strong><br>
        <span style="color:#3b2b6b;font-size:0.9rem">
          Visita <a href="https://checkr.com" style="color:#d3a84f">checkr.com</a> para solicitar
          tu propio informe de antecedentes. Una vez completado, envíanos los resultados por correo.
        </span>
      </div>
      <div style="padding:12px 14px;background:#fff;border-radius:8px;border:1px solid #e4dfef">
        <strong style="color:#1f1333">Opción B — Verificación de Care.com</strong><br>
        <span style="color:#3b2b6b;font-size:0.9rem">
          Si ya tienes una verificación de antecedentes de Care.com, puedes enviárnosla y
          la aceptaremos.
        </span>
      </div>
      <p style="color:#5f5878;font-size:0.85rem;margin:12px 0 0;line-height:1.6">
        Por favor completa tu verificación de antecedentes dentro de los <strong>7 días</strong>
        de haber recibido este correo. Envía los resultados a
        <a href="mailto:dazzleandshinemaids@gmail.com" style="color:#d3a84f">
          dazzleandshinemaids@gmail.com
        </a>
      </p>
    </div>

    <p style="color:#9a95ad;font-size:0.82rem;line-height:1.6;margin:16px 0 0">
      Tu enlace de entrevista es único para ti — por favor no lo compartas.
      ¿Preguntas? Responde a este correo.
    </p>
  </div>

  <!-- FOOTER -->
  <div style="padding:16px 32px;background:#1f1333;border-radius:0 0 12px 12px;text-align:center">
    <p style="color:rgba(255,255,255,0.4);font-size:0.78rem;margin:0">
      {biz} · Questions? Reply to this email.
    </p>
  </div>

</div>"""


def send_interview_invite_email(app_rec):
    """Send the bilingual invite email. Called by admin route and auto-filter timer."""
    biz = 'Dazzle & Shine Maids'
    interview_url = url_for('interviews.interview_page',
                            token=app_rec.interview_token, _external=True)
    send_email(
        to_email=app_rec.email,
        to_name=app_rec.name,
        subject=f"Next Steps: Video Interview + Background Check — {biz}",
        html=_build_invite_html(app_rec.name, interview_url, biz),
    )
