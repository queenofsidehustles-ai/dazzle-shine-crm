import os
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, abort, url_for, flash, redirect
from auth import login_required
from models import ContractorApplication, InterviewResponse
from extensions import db
from notifications import send_email

interviews_bp = Blueprint('interviews', __name__)

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

    interview_url = url_for('interviews.interview_page',
                            token=app_rec.interview_token, _external=True)
    biz = 'Dazzle & Shine Maids'

    html = f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;padding:32px;background:#f6f5fb">
  <div style="background:#1f1333;padding:28px;border-radius:12px;text-align:center;margin-bottom:28px">
    <h1 style="color:#d3a84f;font-family:Georgia,serif;margin:0 0 6px">Dazzle &amp; Shine Maids</h1>
    <p style="color:rgba(255,255,255,0.65);margin:0;font-size:0.9rem;letter-spacing:0.08em">
      Next Step: Video Interview
    </p>
  </div>
  <h2 style="color:#1f1333">Hi {app_rec.name}!</h2>
  <p style="color:#3b2b6b;line-height:1.7">
    Congratulations — you've been selected to move forward in our hiring process!
    The next step is a short <strong>5-question video interview</strong> you can complete
    right from your phone or computer.
  </p>
  <p style="color:#3b2b6b;line-height:1.7">
    <strong>No app download required.</strong> Just click the button below, allow your camera,
    and answer each question at your own pace. It takes about 5–10 minutes total.
  </p>
  <p style="color:#3b2b6b;line-height:1.7">
    A Spanish language option is available on the interview page.
  </p>
  <div style="text-align:center;margin:32px 0">
    <a href="{interview_url}"
       style="background:#d3a84f;color:#1f1333;padding:15px 36px;border-radius:8px;
              text-decoration:none;font-weight:700;font-size:1.05rem;display:inline-block">
      Start My Video Interview
    </a>
  </div>
  <p style="color:#9a95ad;font-size:0.85rem;text-align:center">
    This link is unique to you — please don't share it.
  </p>
  <hr style="border:none;border-top:1px solid #e4dfef;margin:24px 0">
  <p style="color:#9a95ad;font-size:0.8rem">{biz} · Questions? Reply to this email.</p>
</div>"""

    send_email(
        to_email=app_rec.email,
        to_name=app_rec.name,
        subject=f"Your Video Interview Invitation — {biz}",
        html=html,
    )

    flash(f'Interview link sent to {app_rec.name} at {app_rec.email}', 'success')
    return redirect(request.referrer or url_for('interviews.admin_interviews'))
