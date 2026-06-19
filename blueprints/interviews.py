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
    app_rec.status = 'onboarding'
    db.session.commit()
    flash(f'{app_rec.name} approved and moved to onboarding.', 'success')
    return redirect(url_for('interviews.admin_interviews'))


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

    flash(f'{app_rec.name} rejected. Polite email sent to {app_rec.email}.', 'info')
    return redirect(url_for('interviews.admin_interviews'))


@interviews_bp.route('/admin/interviews/send/<int:app_id>', methods=['POST'])
@login_required
def send_invite(app_id):
    app_rec = ContractorApplication.query.get_or_404(app_id)

    if not app_rec.interview_token:
        app_rec.interview_token = secrets.token_urlsafe(32)

    app_rec.interview_status = 'sent'
    app_rec.interview_sent_at = datetime.utcnow()
    db.session.commit()

    send_interview_invite_email(app_rec)

    flash(f'Interview link sent to {app_rec.name} at {app_rec.email}', 'success')
    return redirect(request.referrer or url_for('interviews.admin_interviews'))


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

    <h2 style="color:#1f1333;margin:0 0 12px">Hi {app_rec.name}!</h2>
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

    <h2 style="color:#1f1333;margin:0 0 12px">¡Hola {app_rec.name}!</h2>
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
