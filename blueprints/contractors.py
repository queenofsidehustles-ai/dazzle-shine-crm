import json
import os
import secrets
import threading
from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, request, redirect, url_for, flash, jsonify,
                   current_app, abort)
from entitlements import requires_plan
from auth import login_required, owner_required
from models import (Staff, ContractorApplication, Booking, BookingCrew, BusinessSetting,
                    ContractorPayment, ContractorDocument)
from extensions import db
from notifications import send_email, send_sms
from translate import translate
import stripe_connect
import secure_docs
import branding
import integrations

contractors_bp = Blueprint('contractors', __name__, url_prefix='/contractors')

EXP_LEVELS = [
    ('standard', 'Starting Rate', 50),
    ('top',      'Top Performer', 55),
]

_DEFAULT_TRAINING_GUIDE = """✨ WELCOME TO THE {biz} FAMILY ✨

You didn't just get a gig — you joined a team that takes real pride in what we do. When you clean a home the right way, you're giving someone back their time, their peace of mind, and a space they're proud to come home to. That's the {biz} difference, and now it's yours to deliver.

Read this before your first job, keep it handy, and never be afraid to ask questions. We shine brightest as a team. 💛

━━━━━━━━━━━━━━━━━━━━━━
💛 WHAT MAKES US DIFFERENT — WHO WE ARE
━━━━━━━━━━━━━━━━━━━━━━
Our promise to every client: they come home to a space that sparkles and feels brand new. We treat every home like it's our own.

Three things make you a {biz} pro:
1. CARE — Treat every home, and everything in it, like it's precious.
2. DETAIL — The little touches (a fan-folded towel, a shined faucet, straight throw pillows) are what make clients say "WOW."
3. TRUST — Show up on time, be honest, and protect our clients' privacy and property like family.

Do those three things every time and you'll never run out of work with us.

━━━━━━━━━━━━━━━━━━━━━━
🎥 RECOMMENDED WATCHING
━━━━━━━━━━━━━━━━━━━━━━
Helpful cleaning-technique videos from trusted creators around the web (these aren't ours) — a great way to see pro technique in action before your first job. Watch the routine, then bring it to life the right way:

- How to Clean a Bathroom (Clean My Space): https://www.youtube.com/watch?v=YKpuELbeZQM
- Daily Kitchen Cleaning Routine (Clean My Space): https://www.youtube.com/watch?v=Vos3br2docY
- 20 Brilliant Cleaning Hacks (Clean My Space): https://www.youtube.com/watch?v=vPbgffgCPy0
- 25 Cleaning Tips That Will Blow Your Mind (Clean My Space): https://www.youtube.com/watch?v=RnuvD8I3BQc
- Angela Brown Cleaning — a whole channel that trains professional house cleaners: https://www.youtube.com/channel/UC8OUzZ0rKHOUZ19em4cEXyQ

━━━━━━━━━━━━━━━━━━━━━━
🧴 YOUR SUPPLY CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━
As an independent contractor, you bring your own supplies — think of it as your professional toolkit. Here's what a {biz} pro carries:

Cleaning products:
- All-purpose cleaner
- Glass / window cleaner
- Disinfectant / bathroom cleaner
- Floor cleaner
- Degreaser (for kitchens)
- Toilet bowl cleaner

Tools:
- Microfiber cloths (several — use separate colors for kitchen, bathroom, and glass so you never cross-contaminate)
- Non-scratch sponges & scrub pads
- Vacuum cleaner
- Mop & bucket (or a spray mop)
- Broom & dustpan
- Extendable duster
- Toilet brush
- Rubber gloves
- Trash bags

Nice to have (the pros carry these):
- Grout brush or old toothbrush for detail work
- Squeegee for glass and showers
- Step stool
- A caddy or tote to carry supplies room to room

Tip: Affordable supplies are at Walmart, Dollar Tree, Costco, and Amazon. Buy in bulk to save — you'll go through microfiber cloths and gloves fastest.

━━━━━━━━━━━━━━━━━━━━━━
🧹 OUR METHOD — OUR CLEANING ROUTINE
━━━━━━━━━━━━━━━━━━━━━━
Golden rule: always work TOP TO BOTTOM and LEFT TO RIGHT, so dust falls onto floors you clean last. Never clean the same room twice — do it right the first time.

KITCHEN
- Wipe counters, backsplash, and the outside of appliances
- Clean the stovetop and microwave (inside & out)
- Wipe cabinet fronts; clean and SHINE the sink & faucet (a shiny sink = a happy client)
- Sweep and mop the floor
- Empty the trash

BATHROOMS
- Clean and disinfect the toilet (inside, seat, base)
- Scrub tub/shower and glass until it gleams
- Wipe counter, sink, faucet, and mirror (no streaks!)
- Wipe cabinet fronts
- Sweep and mop the floor
- Empty trash; fan-fold or replace towels if provided

BEDROOMS & LIVING AREAS
- Dust all surfaces, shelves, and décor
- Make beds / tidy as requested
- Wipe mirrors and glass
- Vacuum carpets; sweep/mop hard floors
- Straighten pillows and leave it picture-perfect

WHOLE HOME — THE FINISHING TOUCHES
- Dust ceiling fans, light fixtures, and baseboards
- Wipe light switches, door handles, and high-touch spots
- Spot-clean walls and doors
- Final walkthrough: stand in each doorway and ask, "Would I say WOW?"

━━━━━━━━━━━━━━━━━━━━━━
⭐ OUR STANDARD
━━━━━━━━━━━━━━━━━━━━━━
- Arrive on time, neat, and professional — you represent {biz}
- Treat every home and belonging with care
- Take BEFORE and AFTER photos of every room — it protects you, proves your great work, and earns us 5-star reviews
- If anything is damaged or you miss something, tell us right away — honesty always, no exceptions
- Never use a client's supplies without permission
- Lock up and leave the home secure

━━━━━━━━━━━━━━━━━━━━━━
Welcome aboard. Let's make {city} sparkle, one home at a time. 💛
— The {biz} Family"""


def default_training_guide():
    """The starter welcome guide, with this business's own name in it.

    Kept as a plain template with a {biz} token rather than an f-string: the
    guide is long prose that an owner can rewrite from the Settings page, and a
    stray brace in her wording must never crash the page that renders it."""
    return (_DEFAULT_TRAINING_GUIDE
            .replace('{biz}', branding.biz_name())
            .replace('{city}', branding.city_line() or 'this town'))



@contractors_bp.route('/sms-test')
@login_required
def sms_test():
    """Diagnostic: send a real test text and show exactly what Twilio says."""
    import os as _os
    from models import BusinessSetting
    to = (request.args.get('to') or BusinessSetting.get('owner_alert_phone')
          or _os.environ.get('OWNER_PHONE', ''))
    from_phone = integrations.twilio_phone()

    if not to:
        detail = ('No number to text. Add ?to=+14075551234 to the web address, or set your '
                  'alert phone number in Settings.')
        ok = False
    else:
        ok, detail = send_sms(to, f'{branding.biz_name()} test text ✅ — if you got this, your texting is working!')

    color = '#155724' if ok else '#842029'
    bg = '#d4edda' if ok else '#f8d7da'
    fix_hint = '' if ok else (
        '<div style="margin-top:18px;padding:16px;background:#fff8e1;border:1px solid #f0d488;border-radius:8px;color:#7c4a04;font-size:0.9rem;line-height:1.6">'
        '<strong>Common fixes:</strong><br>'
        '1. Check your account SID, auth token and phone number in '
        '<strong>Settings → Connections</strong>.<br>'
        '2. On a Twilio <strong>trial</strong> account you can only text numbers you\'ve '
        '<strong>verified</strong> in Twilio. Verify your own cell first, or upgrade the account.<br>'
        '3. To text real customers/cleaners at scale you\'ll need Twilio\'s A2P 10DLC '
        'business registration.</div>'
    )
    return (
        f'<div style="font-family:sans-serif;max-width:600px;margin:40px auto;padding:0 16px">'
        f'<div style="background:{bg};color:{color};padding:18px 22px;border-radius:10px;font-weight:700;font-size:1.05rem">'
        f'{"✅ Test text sent!" if ok else "❌ Text did NOT send"}</div>'
        f'<p style="margin-top:16px;color:#1f1333"><strong>To:</strong> {to or "—"}<br>'
        f'<strong>From:</strong> {from_phone or "(TWILIO_PHONE not set)"}<br>'
        f'<strong>Result:</strong> {detail}</p>'
        f'{fix_hint}'
        f'<p style="margin-top:20px"><a href="{url_for("contractors.team")}" style="color:#7c3aed">← Back to Team</a></p>'
        f'</div>'
    )


@contractors_bp.route('/email-test')
@login_required
def email_test():
    """Diagnostic: send a real test email and show exactly what Resend says."""
    import os as _os
    to = request.args.get('to') or BusinessSetting.get('email') or \
        branding.owner_email()
    from_email = branding.from_email()
    has_key = bool(integrations.resend_api_key())

    ok, detail = send_email(
        to_email=to, to_name=branding.biz_name(),
        subject=f'✅ {branding.biz_name()} — Email Test',
        html='<div style="font-family:sans-serif;padding:24px">'
             '<h2 style="color:#1f1333">Your email is working! 🎉</h2>'
             f'<p>If you can read this, {branding.biz_name()} emails are sending correctly.</p></div>',
    )

    color = '#155724' if ok else '#842029'
    bg = '#d4edda' if ok else '#f8d7da'
    # A success here has always been the harder case to act on, not the easier
    # one. "Sent" means Resend accepted the message — it can still be filed as
    # spam or dropped, and this page used to stop at the green box, leaving
    # "it says sent but nothing arrived" with nowhere to go next.
    sent_hint = (
        '<div style="margin-top:18px;padding:16px;background:#eef4ff;border:1px solid #c3d4f5;border-radius:8px;color:#1e3a5f;font-size:0.9rem;line-height:1.6">'
        '<strong>Accepted &mdash; which is not the same as delivered.</strong><br>'
        'Resend has taken the message. Whether it reaches an inbox is up to the '
        'receiving mail server, and the CRM cannot see that from here.<br><br>'
        '<strong>If it does not arrive in a minute or two:</strong><br>'
        '1. Check <strong>spam</strong> and <strong>promotions</strong> &mdash; that '
        'is where it lands most often, and it means the sending domain is not '
        'fully trusted yet.<br>'
        f'2. In Resend &rarr; Domains, confirm the domain of <code>{from_email}</code> '
        'is verified, with its SPF and DKIM records showing green. An unverified '
        'domain is the usual reason mail is accepted and then filtered.<br>'
        '3. Look this exact message up in Resend &rarr; Emails using the id in the '
        'result line above. It will say delivered, bounced or complained.<br>'
        '4. Gmail hides mail it thinks you sent yourself. If you are testing to '
        'the same address you send <em>from</em>, try a different inbox.'
        '</div>'
    ) if ok else ''
    fix_hint = '' if ok else (
        '<div style="margin-top:18px;padding:16px;background:#fff8e1;border:1px solid #f0d488;border-radius:8px;color:#7c4a04;font-size:0.9rem;line-height:1.6">'
        '<strong>How to fix:</strong><br>'
        '1. Check your email service key in <strong>Settings → Connections</strong>'
        f' (currently {"SET" if has_key else "<strong>MISSING</strong>"}).<br>'
        f'2. In your Resend account, verify the sending domain for <code>{from_email}</code>'
        ' (Resend → Domains → Add/Verify). Until the domain is verified, Resend rejects sends.<br>'
        '3. Re-run this test.</div>'
    )
    return (
        f'<div style="font-family:sans-serif;max-width:600px;margin:40px auto;padding:0 16px">'
        f'<div style="background:{bg};color:{color};padding:18px 22px;border-radius:10px;font-weight:700;font-size:1.05rem">'
        f'{"✅ Accepted by the email provider" if ok else "❌ Email did NOT send"}</div>'
        f'<p style="margin-top:16px;color:#1f1333"><strong>To:</strong> {to}<br>'
        f'<strong>From:</strong> {from_email}<br>'
        f'<strong>API key set:</strong> {"yes" if has_key else "no"}<br>'
        f'<strong>Result:</strong> {detail}</p>'
        f'{sent_hint}{fix_hint}'
        f'<p style="margin-top:20px"><a href="{url_for("contractors.team")}" style="color:#7c3aed">← Back to Team</a></p>'
        f'</div>'
    )


# ── Applications ───────────────────────────────────────────────────────────────

SOURCES = ['Indeed', 'Facebook', 'Nextdoor', 'Craigslist', 'Referral', 'Walk-in', 'Website', 'Other']


def _reconcile_hired():
    """Self-heal the pipeline. 'Hired' means the background check has cleared, so:
    promote cleared-BG applicants to Hired, and back-link any Team (Staff) record to
    its application. Runs cheaply each time the Applications page loads."""
    changed = 0
    apps = ContractorApplication.query.filter(
        ContractorApplication.status.in_(['new', 'reviewing'])).all()
    for a in apps:
        s = Staff.query.filter(db.func.lower(Staff.email) == a.email.lower()).first() if a.email else None
        if s and hasattr(s, 'application_id') and not s.application_id:
            s.application_id = a.id
            changed += 1
        # Only a cleared background check promotes to Hired.
        if a.background_check_status == 'cleared':
            a.status = 'hired'
            changed += 1
    if changed:
        db.session.commit()
    return changed


@contractors_bp.route('/applications')
@login_required
@requires_plan('hiring')
def applications():
    _reconcile_hired()
    status_filter = request.args.get('status', '')
    # "Awaiting BG Check" = the holding space: an offer is out but they aren't hired
    # (BG not cleared) or rejected yet. Covers offer-sent, accepted, and BG-in-review.
    awaiting_filter = (ContractorApplication.offer_sent_at.isnot(None),
                       ContractorApplication.status.notin_(['hired', 'rejected']))
    q = ContractorApplication.query.order_by(ContractorApplication.created_at.desc())
    if status_filter == 'awaiting_bg':
        q = q.filter(*awaiting_filter)
    elif status_filter:
        q = q.filter_by(status=status_filter)
    apps = q.all()
    counts = {
        'all': ContractorApplication.query.count(),
        'new': ContractorApplication.query.filter_by(status='new').count(),
        'reviewing': ContractorApplication.query.filter_by(status='reviewing').count(),
        'awaiting_bg': ContractorApplication.query.filter(*awaiting_filter).count(),
        'hired': ContractorApplication.query.filter_by(status='hired').count(),
        'rejected': ContractorApplication.query.filter_by(status='rejected').count(),
        'no_response': ContractorApplication.query.filter_by(status='no_response').count(),
    }
    apply_url = url_for('contractors.apply', _external=True)
    return render_template('admin/applications.html', apps=apps,
                           counts=counts, status_filter=status_filter,
                           apply_url=apply_url, sources=SOURCES)


@contractors_bp.route('/applications/merge-duplicates', methods=['POST'])
@login_required
def merge_duplicates():
    """Combine repeat applications (same email) into one card per person.
    Keeps the card furthest along in the pipeline; moves over any video
    answers the keeper is missing, then deletes the extras."""
    from models import InterviewResponse  # noqa: F401 (relationship use)
    STATUS_RANK = {'hired': 5, 'onboarding': 5, 'reviewing': 3, 'new': 2, 'no_response': 1, 'rejected': 0}
    IV_RANK = {'completed': 4, 'in_progress': 3, 'sent': 2, 'pending': 1, 'not_sent': 0}

    def score(a):
        return STATUS_RANK.get(a.status, 2) * 10 + IV_RANK.get(a.interview_status or 'not_sent', 0)

    groups = {}
    for a in ContractorApplication.query.all():
        key = (a.email or '').strip().lower()
        if key:
            groups.setdefault(key, []).append(a)

    merged = 0
    people = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        people += 1
        keeper = max(group, key=lambda a: (score(a), a.created_at or datetime.min))
        for dup in group:
            if dup.id == keeper.id:
                continue
            # Fill blanks on the keeper from the duplicate
            for f in ('name', 'phone', 'years_experience', 'services', 'availability',
                      'why_interested', 'bgcheck_existing_link', 'source'):
                if not getattr(keeper, f, None) and getattr(dup, f, None):
                    setattr(keeper, f, getattr(dup, f))
            # Move over any interview answers the keeper doesn't already have
            answered = {r.question_index for r in keeper.responses}
            for r in list(dup.responses):
                if r.question_index in answered:
                    db.session.delete(r)
                else:
                    r.application_id = keeper.id
                    answered.add(r.question_index)
            _d = dup.created_at.strftime('%b %d') if dup.created_at else '?'
            keeper.admin_notes = ((keeper.admin_notes or '') + f"\nMerged duplicate applied {_d}.").strip()
            db.session.delete(dup)
            merged += 1

    db.session.commit()
    if merged:
        flash(f'Merged {merged} duplicate card(s) across {people} applicant(s). ✨', 'success')
    else:
        flash('No duplicates found — your list is already clean! 🎉', 'success')
    return redirect(url_for('contractors.applications'))


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
    biz = branding.biz_name()
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
    biz = branding.biz_name()
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
    biz = branding.biz_name()
    owner_email = branding.owner_email()
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
    biz = branding.biz_name()
    owner_email = branding.owner_email()
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
    biz = branding.biz_name()
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
            # Clearing the background check is the gate to "Hired" — a conditional
            # offer only becomes a real hire once the check clears.
            if a.background_check_status == 'cleared' and a.status not in ('rejected',):
                a.status = 'hired'
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
        language=getattr(a, 'language', 'en') or 'en',
    )
    token = secrets.token_urlsafe(32)
    s.agreement_token = token
    db.session.add(s)
    db.session.flush()          # get s.id so we can link the application
    if hasattr(s, 'application_id'):
        s.application_id = a.id
    _carry_documents_to_staff(a, s)
    a.status = 'hired'
    db.session.commit()

    if s.email:
        import os
        biz = branding.biz_name()
        owner_email = branding.owner_email()
        hub_url = url_for('contractors.onboarding_hub', token=token, _external=True, _scheme='https')
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
    <p>We're excited to have you on board! Everything you need to get started is on one page — just tap below to:</p>
    <ol style="line-height:2;color:#3b2460">
      <li><strong>Sign your work agreement</strong></li>
      <li><strong>Set up how you get paid</strong> (secure bank + tax setup through Stripe)</li>
      <li><strong>Choose your pay schedule and start date</strong></li>
      <li><strong>Review your Training &amp; Supply Guide</strong></li>
    </ol>
    <div style="text-align:center;margin:28px 0">
      <a href="{hub_url}" style="background:#d3a84f;color:#1f1333;padding:14px 32px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;display:inline-block">
        Complete My Onboarding →
      </a>
    </div>
    <p style="font-size:0.82rem;color:#9a95ad">Link not working? Copy and paste: {hub_url}</p>
    <p>Questions? Reply to this email or call us directly. We're here to set you up for success.</p>
    <p style="margin-bottom:0">Welcome aboard,<br>
    <strong style="color:#b98a33">{biz}</strong><br>
    <a href="mailto:{owner_email}" style="color:#7c3aed">{owner_email}</a></p>
  </div>
</div>""",
        )

    flash(f'{a.name} has been added to your team!', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=s.id))


# ── Offer acceptance + Stripe onboarding ───────────────────────────────────────

def _notify_owner(subject, html):
    """Send the business owner an internal alert email (best-effort)."""
    import os
    owner = (BusinessSetting.get('email') or os.environ.get('OWNER_EMAIL')
             or branding.owner_email())
    try:
        send_email(to_email=owner, to_name=branding.biz_name(), subject=subject, html=html)
    except Exception:
        pass


def _sync_stripe_status(s):
    """Pull the contractor's latest Stripe status onto the Staff record."""
    if not s or not s.stripe_account_id:
        return
    ok, data = stripe_connect.get_account_status(s.stripe_account_id)
    if not ok:
        return
    was_enabled = bool(s.stripe_payouts_enabled)
    s.stripe_payouts_enabled = data['payouts_enabled']
    s.stripe_details_submitted = data['details_submitted']
    s.stripe_disabled_reason = data.get('disabled_reason')
    if s.stripe_payouts_enabled:
        steps = s.get_onboarding()
        if 'payment_info' not in steps:
            steps.append('payment_info')
            s.onboarding_steps = json.dumps(steps)
    db.session.commit()
    # Alert the owner the first time this contractor becomes payable
    if s.stripe_payouts_enabled and not was_enabled:
        _notify_owner(
            f'✅ {s.name} finished payment setup — ready to be paid',
            f'<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1f1333">'
            f'<h2 style="color:#276749">{s.name} is ready to get paid 💰</h2>'
            f'<p>They completed their Stripe payment setup and are now verified. '
            f'You can send them payouts from their Team profile.</p></div>')


@contractors_bp.route('/offer/accept/<token>')
def accept_offer(token):
    """Public link from the conditional-offer email. Records acceptance, creates
    the Team member + their Stripe account, then sends them to the onboarding hub."""
    a = ContractorApplication.query.filter_by(offer_token=token).first_or_404()

    # Find or create the Staff record for this person (avoid duplicates)
    s = None
    if a.email:
        s = Staff.query.filter(db.func.lower(Staff.email) == a.email.lower()).first()
    if not s:
        s = Staff(
            name=a.name, email=a.email, phone=a.phone,
            pay_type='percent', pay_rate=50.0, experience_level='standard',
            has_transportation=a.has_transportation, has_supplies=a.has_supplies,
            worker_model=BusinessSetting.get('worker_model', 'contractor'),
            color='#7c3aed', is_active=True,
            language=getattr(a, 'language', 'en') or 'en',
        )
        s.agreement_token = secrets.token_urlsafe(32)
        db.session.add(s)

    if not a.offer_accepted_at:
        a.offer_accepted_at = datetime.utcnow()
    # Conditional offer accepted — they can START onboarding, but stay in the
    # Reviewing holding pen until their background check clears (the gate to Hired).
    if a.status not in ('hired', 'rejected'):
        a.status = 'reviewing'
    if hasattr(s, 'application_id') and not s.application_id:
        s.application_id = a.id
    db.session.flush()                   # need s.id before documents can point at it
    _carry_documents_to_staff(a, s)
    if not s.agreement_token:            # existing staff may not have one yet
        s.agreement_token = secrets.token_urlsafe(32)
    db.session.commit()

    # Create their Stripe connected account if they don't have one yet
    if not s.stripe_account_id and stripe_connect.is_configured():
        ok, result = stripe_connect.create_express_account(s.email, s.name)
        if ok:
            s.stripe_account_id = result
            db.session.commit()

    return redirect(url_for('contractors.onboarding_hub', token=s.agreement_token))


@contractors_bp.route('/onboarding/<token>')
def onboarding_hub(token):
    """One page for the new contractor: sign agreement + set up Stripe payments."""
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    biz = branding.biz_name()
    _sync_stripe_status(s)   # refresh in case they just came back from Stripe
    return render_template('public/onboarding_hub.html', s=s, biz=biz,
                           stripe_configured=stripe_connect.is_configured())


DOC_COPY = {
    'id': {
        'title': 'Send a photo of your ID',
        'title_es': 'Envía una foto de tu identificación',
        'lead': ("You'll be going into people's homes, so we keep a photo ID on file for every cleaner "
                 "on the team. A driver's licence, state ID or passport is fine."),
        'lead_es': ("Vas a entrar a las casas de nuestros clientes, así que guardamos una identificación "
                    "con foto de cada limpiador del equipo. Una licencia de conducir, identificación "
                    "estatal o pasaporte funciona."),
        'steps': [
            ("Lay it flat in good light and take a photo, or scan it to a PDF.",
             "Ponla sobre una superficie plana con buena luz y tómale una foto, o escanéala a PDF."),
            ("Check all four corners are in the picture and the text is readable.",
             "Revisa que se vean las cuatro esquinas y que el texto se pueda leer."),
            ("Upload it below.", "Súbela abajo."),
        ],
    },
    'w9': {
        'title': 'Send your W-9',
        'title_es': 'Envía tu W-9',
        'lead': ("You're paid without tax withheld, so we need a Form W-9 on file to report what we paid "
                 "you at the end of the year. It's one page and it's free."),
        'lead_es': ("Se te paga sin retención de impuestos, así que necesitamos un Formulario W-9 "
                    "archivado para reportar tu pago al final del año. Es una página y es gratis."),
        'steps': [
            ('Download the blank form from the IRS: <a class="gold" href="https://www.irs.gov/pub/irs-pdf/fw9.pdf" '
             'target="_blank" rel="noopener">irs.gov/pub/irs-pdf/fw9.pdf</a>',
             'Descarga el formulario en blanco del IRS.'),
            ("Fill in your name, address and your SSN or EIN, then sign and date it.",
             "Llénalo con tu nombre, dirección y tu SSN o EIN, luego fírmalo y ponle la fecha."),
            ("Upload it below — a PDF or a clear photo of the signed form is fine.",
             "Súbelo abajo — un PDF o una foto clara del formulario firmado está bien."),
        ],
    },
}


def _carry_documents_to_staff(app_rec, staff):
    """Move an applicant's documents onto their Staff row when they're hired.

    A background check is uploaded before there is a Staff row to hang it on, so
    it lands on the application. Leaving it there would mean the one place the
    owner looks for a cleaner's paperwork — their profile — is missing the
    document that mattered most before they were let into anyone's home."""
    for doc in list(app_rec.documents):
        if staff.document(doc.kind):
            continue          # they already sent a newer one directly
        doc.staff_id = staff.id
        doc.application_id = None


@contractors_bp.route('/documents/<token>/<kind>', methods=['GET', 'POST'])
def upload_document(token, kind):
    """Where a contractor sends a photo ID or a W-9.

    The file is posted here rather than straight to Cloudinary like the job
    photos are. Cloudinary hands back a public URL, which is the right trade for
    a picture of a clean kitchen and the wrong one for a government ID — so
    these go into the encrypted store instead and never get a public address at
    all. Plain form POST, no JavaScript: this gets opened on a phone, from a
    text message, sometimes on a bad connection."""
    if kind not in DOC_COPY:
        abort(404)
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    existing = s.document(kind)

    if request.method == 'POST':
        ok, err, ctype, raw = secure_docs.check_upload(request.files.get('document'))
        if not ok:
            flash(err, 'error')
            return redirect(url_for('contractors.upload_document', token=token, kind=kind))

        blob = secure_docs.encrypt(raw)
        if existing:
            existing.data = blob
            existing.filename = request.files['document'].filename[:200]
            existing.content_type = ctype
            existing.size_bytes = len(raw)
            existing.uploaded_at = datetime.utcnow()
        else:
            db.session.add(ContractorDocument(
                staff_id=s.id, kind=kind,
                filename=request.files['document'].filename[:200],
                content_type=ctype, size_bytes=len(raw), data=blob,
            ))
        if kind == 'w9':
            s.w9_uploaded_at = datetime.utcnow()
        db.session.commit()

        label = dict(ContractorDocument.KINDS).get(kind, kind)
        try:
            send_email(
                to_email=branding.owner_email(), to_name=branding.biz_name(),
                subject=f"{label} received — {s.name}",
                html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;padding:24px">
  <h2 style="color:#1f1333">{s.name} sent their {label.lower()}</h2>
  <p style="color:#3b2b6b">It's stored encrypted against their profile.</p>
  <p style="color:#3b2b6b"><a href="{url_for('contractors.staff_detail', staff_id=s.id, _external=True)}"
     style="color:#d3a84f;font-weight:700">Open {s.name}'s profile →</a></p>
</div>""",
            )
        except Exception:
            pass
        return redirect(url_for('contractors.upload_document', token=token, kind=kind, sent=1))

    return render_template('public/document_upload.html', s=s, token=token, kind=kind,
                           copy=DOC_COPY[kind], existing=existing,
                           just_sent=request.args.get('sent') == '1',
                           max_mb=secure_docs.MAX_BYTES // (1024 * 1024))


def _document_owner_url(doc):
    """Back to whoever the document belongs to — a hired cleaner or an
    applicant who hasn't been hired yet."""
    if doc.staff_id:
        return url_for('contractors.staff_detail', staff_id=doc.staff_id)
    if doc.application_id:
        return url_for('contractors.application_detail', app_id=doc.application_id)
    return url_for('contractors.team')


@contractors_bp.route('/documents/<int:doc_id>/view')
@owner_required
def view_document(doc_id):
    """The only way a stored document comes back out, and it needs the owner's
    login. Streamed from the database rather than redirected to a file host, so
    there is no URL that works once this response is over."""
    doc = ContractorDocument.query.get_or_404(doc_id)
    raw = secure_docs.decrypt(doc.data)
    if raw is None:
        flash('That document could not be decrypted — SECRET_KEY has changed since it was '
              'uploaded. Ask them to send it again.', 'error')
        return redirect(_document_owner_url(doc))
    ext = secure_docs.ALLOWED_TYPES.get(doc.content_type, 'bin')
    safe_name = f"{(doc.owner_name or 'document').replace(' ', '-').lower()}-{doc.kind}.{ext}"
    resp = current_app.response_class(raw, mimetype=doc.content_type or 'application/octet-stream')
    resp.headers['Content-Disposition'] = f'inline; filename="{safe_name}"'
    # Not for caches or history — this is the whole point of the route.
    resp.headers['Cache-Control'] = 'private, no-store, max-age=0'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    return resp


@contractors_bp.route('/documents/<int:doc_id>/delete', methods=['POST'])
@owner_required
def delete_document(doc_id):
    doc = ContractorDocument.query.get_or_404(doc_id)
    label, back = doc.label, _document_owner_url(doc)
    db.session.delete(doc)
    db.session.commit()
    flash(f'{label} deleted.', 'success')
    return redirect(request.referrer or back)


@contractors_bp.route('/documents/request/<int:staff_id>/<kind>', methods=['POST'])
@owner_required
def request_document(staff_id, kind):
    """Text and email one cleaner the link to send a document."""
    if kind not in DOC_COPY:
        abort(404)
    s = Staff.query.get_or_404(staff_id)
    if not s.agreement_token:
        s.agreement_token = secrets.token_urlsafe(32)
        db.session.commit()
    link = f"{branding.crm_base()}/contractors/documents/{s.agreement_token}/{kind}"
    biz = branding.biz_name()
    label = dict(ContractorDocument.KINDS).get(kind, kind)
    sent = []

    if s.phone:
        if kind == 'id':
            msg = (f"Hi {s.name.split()[0]} — {biz} keeps a photo ID on file for everyone on the team. "
                   f"Send yours here, it takes a minute: {link}")
        else:
            msg = (f"Hi {s.name.split()[0]} — {biz} needs a Form W-9 on file so we can report your pay "
                   f"at year end. It takes a few minutes: {link}")
        if (s.language or 'en') == 'es':
            msg = translate(msg, target='es')
        try:
            ok, _ = send_sms(s.phone, msg)
            if ok:
                sent.append('text')
        except Exception:
            pass

    if s.email:
        try:
            send_email(
                to_email=s.email, to_name=s.name,
                subject=f"Please send us your {label.lower()} — {biz}",
                html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">One quick thing, {s.name.split()[0]}</h2>
  <p style="line-height:1.7">{DOC_COPY[kind]['lead']}</p>
  <p style="line-height:1.7;color:#5f5878;font-size:0.92rem">{DOC_COPY[kind]['lead_es']}</p>
  <p style="text-align:center;margin:24px 0">
    <a href="{link}" style="background:#1f1333;color:#d3a84f;padding:14px 30px;border-radius:8px;
       text-decoration:none;font-weight:700">📄 Send it here →</a>
  </p>
  <p style="color:#5f5878;font-size:0.84rem;line-height:1.6">It's stored securely and used only for our
  records — we never share it with customers.</p>
  <p style="color:#9a95ad;font-size:12px">{biz}</p>
</div>""",
            )
            sent.append('email')
        except Exception:
            pass

    if kind == 'w9':
        s.w9_requested_at = datetime.utcnow()
        db.session.commit()

    if sent:
        flash(f"{label} request sent to {s.name} by {' and '.join(sent)}.", 'success')
    else:
        flash(f"Couldn't reach {s.name} — no phone or email on file.", 'error')
    return redirect(request.referrer or url_for('contractors.staff_detail', staff_id=s.id))


@contractors_bp.route('/w9/<token>')
def w9_upload(token):
    """Superseded by the encrypted document store. Kept so a link that has
    already gone out by text doesn't dead-end."""
    return redirect(url_for('contractors.upload_document', token=token, kind='w9'))


@contractors_bp.route('/onboarding/<token>/payments')
def onboarding_payments(token):
    """Create a Stripe hosted-onboarding link and send the contractor to it."""
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    if not stripe_connect.is_configured():
        flash('Payments are not set up yet — please contact us.', 'warning')
        return redirect(url_for('contractors.onboarding_hub', token=token))
    if not s.stripe_account_id:
        ok, result = stripe_connect.create_express_account(s.email, s.name)
        if not ok:
            flash(f'Payment setup could not start: {result}', 'error')
            return redirect(url_for('contractors.onboarding_hub', token=token))
        s.stripe_account_id = result
        db.session.commit()
    hub_url = url_for('contractors.onboarding_hub', token=token, _external=True, _scheme='https')
    ok, link = stripe_connect.create_onboarding_link(s.stripe_account_id, hub_url, hub_url)
    if not ok:
        flash(f'Payment setup could not open: {link}', 'error')
        return redirect(url_for('contractors.onboarding_hub', token=token))
    return redirect(link)


@contractors_bp.route('/onboarding/<token>/pay-schedule', methods=['POST'])
def onboarding_pay_schedule(token):
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    s.pay_schedule = 'weekly' if request.form.get('pay_schedule') == 'weekly' else 'daily'
    db.session.commit()
    return redirect(url_for('contractors.onboarding_hub', token=token))


@contractors_bp.route('/onboarding/<token>/start-date', methods=['POST'])
def onboarding_start_date(token):
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    s.roster_start_date = request.form.get('roster_start_date', '').strip()
    db.session.commit()
    return redirect(url_for('contractors.onboarding_hub', token=token))


def _open_entry(booking_id, staff_id):
    """This cleaner's running spell on this job, if they are clocked in."""
    from models import TimeEntry
    return (TimeEntry.query
            .filter_by(booking_id=booking_id, staff_id=staff_id,
                       clock_out_at=None)
            .order_by(TimeEntry.id.desc()).first())


@contractors_bp.route('/my-day/<token>/clock-in/<int:booking_id>', methods=['POST'])
def clock_in(token, booking_id):
    """Start the clock for the cleaner holding this link.

    The token says who they are, which is why this lives on My Day rather than
    on the checklist: a checklist belongs to the job and cannot tell one member
    of a crew from another.
    """
    from models import TimeEntry
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    b = Booking.query.get_or_404(booking_id)

    # Already running? Do nothing rather than open a second spell. Somebody
    # double-tapping on a phone with a poor signal must not end up being paid
    # twice for the same hour.
    if not _open_entry(b.id, s.id):
        db.session.add(TimeEntry(booking_id=b.id, staff_id=s.id,
                                 clock_in_at=datetime.utcnow()))
        db.session.commit()
    return redirect(url_for('contractors.my_day', token=token))


@contractors_bp.route('/my-day/<token>/clock-out/<int:booking_id>', methods=['POST'])
def clock_out(token, booking_id):
    """Stop the clock. Closes only the spell that is actually open."""
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    b = Booking.query.get_or_404(booking_id)
    entry = _open_entry(b.id, s.id)
    if entry:
        entry.clock_out_at = datetime.utcnow()
        db.session.commit()
    return redirect(url_for('contractors.my_day', token=token))


@contractors_bp.route('/my-day/<token>')
def my_day(token):
    """A cleaner's personal daily job board — today + next 7 days, with navigate,
    access notes, payout, and checklist links. Public, token-gated per cleaner."""
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    today = date.today()
    horizon = (today + timedelta(days=7)).isoformat()
    # Their solo jobs plus any crew job they hold a spot on (they may not be the lead).
    jobs = Booking.query.outerjoin(BookingCrew, BookingCrew.booking_id == Booking.id).filter(
        db.or_(db.func.lower(Booking.assigned_cleaner) == (s.name or '').lower(),
               BookingCrew.staff_id == s.id),
        Booking.status != 'cancelled',
        Booking.preferred_date >= today.isoformat(),
        Booking.preferred_date <= horizon,
    ).distinct().order_by(Booking.preferred_date, Booking.preferred_time).all()
    days = {}
    for b in jobs:
        days.setdefault(b.preferred_date, []).append(b)
    # The keys stay ISO because the template compares them against today, but
    # nobody reads "2026-08-30" off a phone screen at seven in the morning.
    labels = {}
    for iso in days:
        try:
            d = date.fromisoformat(iso)
        except (TypeError, ValueError):
            labels[iso] = iso or 'Date to be confirmed'
            continue
        delta = (d - today).days
        if delta == 0:
            labels[iso] = 'Today'
        elif delta == 1:
            labels[iso] = 'Tomorrow'
        else:
            labels[iso] = d.strftime('%A %-d %B')
    # Per job: is this cleaner's clock running, and what have they logged so
    # far. Worked out here rather than in the template so the page stays a
    # page and does not start querying.
    clocked = {}
    for b in jobs:
        clocked[b.id] = {
            'open': _open_entry(b.id, s.id) is not None,
            'hours': s.hours_on(b),
        }

    # Whose language this page is in: the cleaner holding the link. A toggle
    # on the page still overrides it for this browser.
    import i18n
    i18n.set_person(s)

    biz = branding.biz_name()
    return render_template('public/my_day.html', s=s, days=days,
                           day_labels=labels, today=today.isoformat(),
                           clocked=clocked, biz=biz)


@contractors_bp.route('/sample-day')
def sample_day():
    """A demo 'My Day' with one made-up job — for showing new hires the layout."""
    from pricing import get_labor_rate

    class _FakeStaff:
        name = 'Maria'

    class _FakeJob:
        """Stands in for a real Booking on the demo page — it has to answer the
        same questions the template asks of a real one."""
        job_checklists = []
        lead_fee = 0
        crew = []
        crew_size = 1
        is_crew_job = False
        crew_names = []
        def __init__(self, **kw):
            self.__dict__.update(kw)
        @property
        def service_label(self):
            return 'Standard House Cleaning'
        @property
        def commissionable_price(self):
            return round((self.price or 0) - (self.lead_fee or 0), 2)
        @property
        def labor_budget(self):
            return round((self.estimated_hours or 0) * get_labor_rate(), 2)
        def crew_row_for(self, staff):
            return None
        def pay_for(self, staff):
            return self.labor_budget

    today = date.today()
    job = _FakeJob(preferred_time='10:00 AM', name='The Johnson Family', bedrooms='3',
                   bathrooms='2', address='123 Palm Ave', city=(branding.city_line() or 'Your City'), zip_code='',
                   price=180, hours_worked=0, estimated_hours=3.0,
                   access_notes='Gate code 1234 · key under the blue mat · friendly dog named Max 🐶')
    days = {today.isoformat(): [job]}
    biz = branding.biz_name()
    return render_template('public/my_day.html', s=_FakeStaff(), days=days,
                           today=today.isoformat(), biz=biz)


@contractors_bp.route('/start-date/<token>', methods=['GET', 'POST'])
def confirm_start_date(token):
    """Public, token-gated page where a new hire picks/confirms their start date."""
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    biz = branding.biz_name()
    if request.method == 'POST':
        chosen = (request.form.get('start_date') or '').strip()
        if chosen:
            s.roster_start_date = chosen
            db.session.commit()
            phone = BusinessSetting.get('owner_alert_phone') or BusinessSetting.get('phone')
            if phone:
                try:
                    send_sms(phone, f"📅 {s.name} confirmed their start date: {chosen}.")
                except Exception:
                    pass
            return render_template('public/start_date.html', s=s, biz=biz,
                                   saved=True, chosen=chosen, today=date.today().isoformat())
    return render_template('public/start_date.html', s=s, biz=biz, saved=False,
                           chosen=s.roster_start_date or '', today=date.today().isoformat())


@contractors_bp.route('/onboarding/<token>/guide')
def onboarding_guide(token):
    """Public training & supply guide the contractor reviews during onboarding."""
    s = Staff.query.filter_by(agreement_token=token).first_or_404()
    biz = branding.biz_name()
    guide = BusinessSetting.get('training_guide') or default_training_guide()
    # Escape first (safe from any HTML in the owner-edited text), then linkify URLs.
    import html as _html, re as _re
    guide_html = _re.sub(r'(https?://[^\s]+)',
                         r'<a href="\1" target="_blank" style="color:#7c3aed;word-break:break-all">\1</a>',
                         _html.escape(guide))
    return render_template('public/training_guide.html', s=s, biz=biz, guide_html=guide_html)


@contractors_bp.route('/training-guide', methods=['GET', 'POST'])
@login_required
def training_guide():
    """Owner edits the training & supply guide contractors see during onboarding."""
    if request.method == 'POST':
        BusinessSetting.set('training_guide', request.form.get('guide', '').strip())
        db.session.commit()
        flash('Training & Supply Guide saved!', 'success')
        return redirect(url_for('contractors.training_guide'))
    guide = BusinessSetting.get('training_guide') or default_training_guide()
    return render_template('admin/training_guide_edit.html', guide=guide)


# ── Paying contractors ─────────────────────────────────────────────────────────

@contractors_bp.route('/team/<int:staff_id>/refresh-stripe', methods=['POST'])
@login_required
def refresh_stripe(staff_id):
    s = Staff.query.get_or_404(staff_id)
    _sync_stripe_status(s)
    flash('Payment status refreshed.', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=staff_id))


@contractors_bp.route('/team/<int:staff_id>/pay', methods=['POST'])
@login_required
def pay_contractor(staff_id):
    s = Staff.query.get_or_404(staff_id)
    try:
        amount = round(float(request.form.get('amount', 0)), 2)
    except (TypeError, ValueError):
        amount = 0
    note = request.form.get('note', '').strip()
    if amount <= 0:
        flash('Enter an amount greater than $0.', 'error')
        return redirect(url_for('contractors.staff_detail', staff_id=staff_id))

    _sync_stripe_status(s)
    if not (s.stripe_account_id and s.stripe_payouts_enabled):
        flash(f"{s.name} isn't verified on Stripe yet, so we can't send a Stripe payment.", 'warning')
        return redirect(url_for('contractors.staff_detail', staff_id=staff_id))

    ok, result = stripe_connect.create_transfer(
        s.stripe_account_id, amount, description=f'Payout to {s.name}')
    if not ok:
        flash(f'Stripe payment failed: {result}', 'error')
        return redirect(url_for('contractors.staff_detail', staff_id=staff_id))

    db.session.add(ContractorPayment(
        staff_id=s.id, amount=amount, method='stripe',
        status='paid', stripe_transfer_id=result, note=note))
    db.session.commit()
    flash(f'✅ Sent ${amount:.2f} to {s.name} via Stripe.', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=staff_id))


@contractors_bp.route('/team/<int:staff_id>/pay-manual', methods=['POST'])
@login_required
def pay_manual(staff_id):
    """Record a payment made outside Stripe (Venmo/Zelle/cash/check)."""
    s = Staff.query.get_or_404(staff_id)
    try:
        amount = round(float(request.form.get('amount', 0)), 2)
    except (TypeError, ValueError):
        amount = 0
    method = request.form.get('method', 'venmo')
    note = request.form.get('note', '').strip()
    if amount <= 0:
        flash('Enter an amount greater than $0.', 'error')
        return redirect(url_for('contractors.staff_detail', staff_id=staff_id))
    db.session.add(ContractorPayment(
        staff_id=s.id, amount=amount, method=method, status='paid', note=note))
    db.session.commit()
    flash(f'Recorded ${amount:.2f} paid to {s.name} via {method.title()}.', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=staff_id))


# ── Delete (clean up test entries) ─────────────────────────────────────────────

@contractors_bp.route('/applications/<int:app_id>/delete', methods=['POST'])
@login_required
def delete_application(app_id):
    from models import InterviewResponse
    a = ContractorApplication.query.get_or_404(app_id)
    name = a.name
    InterviewResponse.query.filter_by(application_id=a.id).delete()
    db.session.delete(a)
    db.session.commit()
    flash(f'Deleted application: {name}.', 'success')
    return redirect(url_for('contractors.applications'))


@contractors_bp.route('/team/<int:staff_id>/delete', methods=['POST'])
@login_required
def delete_staff(staff_id):
    s = Staff.query.get_or_404(staff_id)
    name = s.name
    ContractorPayment.query.filter_by(staff_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()
    flash(f'Removed team member: {name}.', 'success')
    return redirect(url_for('contractors.team'))


# ── Team / Contractor Profiles ─────────────────────────────────────────────────

@contractors_bp.route('/team')
@login_required
def team():
    staff = Staff.query.order_by(Staff.is_active.desc(), Staff.name).all()
    return render_template('admin/team.html', staff=staff, exp_levels=EXP_LEVELS)


@contractors_bp.route('/team/<int:staff_id>/language', methods=['POST'])
@login_required
def set_staff_language(staff_id):
    s = Staff.query.get_or_404(staff_id)
    lang = request.form.get('language', 'en')
    s.language = 'es' if lang == 'es' else 'en'
    db.session.commit()
    flash(f"{s.name} set to {'Spanish 🇪🇸 — messages will auto-translate' if s.language=='es' else 'English 🇺🇸'}.", 'success')
    return redirect(request.referrer or url_for('contractors.staff_detail', staff_id=staff_id))


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
        # Which card was submitted? Only touch that card's fields so, e.g., the
        # "Update Pay" form never wipes checkboxes it doesn't contain.
        section = request.form.get('section', 'profile')
        if section == 'pay':
            s.experience_level = request.form.get('experience_level', s.experience_level)
            s.pay_type = request.form.get('pay_type', s.pay_type)
            if (request.form.get('pay_rate') or '') != '':
                s.pay_rate = float(request.form.get('pay_rate'))
        else:  # profile card
            s.name = request.form.get('name', s.name).strip()
            s.phone = request.form.get('phone', s.phone or '').strip()
            s.email = request.form.get('email', s.email or '').strip()
            s.emergency_contact_name = request.form.get('emergency_contact_name', s.emergency_contact_name or '').strip()
            s.emergency_contact_phone = request.form.get('emergency_contact_phone', s.emergency_contact_phone or '').strip()
            s.roster_start_date = request.form.get('roster_start_date', s.roster_start_date or '').strip()
            s.pay_schedule = request.form.get('pay_schedule', s.pay_schedule or 'daily')
            s.has_transportation = 'has_transportation' in request.form
            s.has_supplies = 'has_supplies' in request.form
            s.is_active = 'is_active' in request.form
            s.color = request.form.get('color', s.color)
            s.notes = request.form.get('notes', s.notes or '').strip()
        db.session.commit()
        flash('Saved!', 'success')
        return redirect(url_for('contractors.staff_detail', staff_id=staff_id))
    if s.stripe_account_id:
        _sync_stripe_status(s)   # auto-refresh payment status on page load
    recent_jobs = Booking.query.filter_by(assigned_cleaner=s.name, status='completed').order_by(Booking.created_at.desc()).limit(10).all()
    return render_template('admin/contractor_detail.html', s=s, recent_jobs=recent_jobs,
                           exp_levels=EXP_LEVELS, secure_docs_ready=secure_docs.is_ready())


@contractors_bp.route('/team/<int:staff_id>/toggle', methods=['POST'])
@login_required
def staff_toggle_active(staff_id):
    """One-click activate/deactivate. Deactivating silently removes the cleaner
    from job broadcasts, the assignment dropdown, work orders, and payroll.
    No text or email is ever sent to the team member."""
    s = Staff.query.get_or_404(staff_id)
    s.is_active = not s.is_active
    db.session.commit()
    if s.is_active:
        flash(f'{s.name} is active again and can receive job assignments.', 'success')
    else:
        flash(f'{s.name} has been deactivated — they will no longer receive job assignments or notifications. No message was sent to them.', 'success')
    return redirect(url_for('contractors.staff_detail', staff_id=staff_id))


# ── Payroll ────────────────────────────────────────────────────────────────────

@contractors_bp.route('/timesheet')
@owner_required
@requires_plan('payroll')
def timesheet():
    """Hours worked per cleaner for a week, from the clock.

    Deliberately hours and nothing else. No overtime, no break deduction, no
    state rounding rules — those are regulated, they differ by state, and the
    terms of service say plainly that this is not a payroll provider. What a
    business needs from us is an accurate record of who worked when; their
    payroll provider applies the rules to it.
    """
    from models import TimeEntry
    today = date.today()
    start_str = request.args.get(
        'start', (today - timedelta(days=today.weekday())).isoformat())
    try:
        start = date.fromisoformat(start_str)
    except ValueError:
        start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)

    entries = (TimeEntry.query
               .filter(TimeEntry.clock_in_at >= datetime.combine(start, datetime.min.time()),
                       TimeEntry.clock_in_at < datetime.combine(end + timedelta(days=1),
                                                                datetime.min.time()))
               .order_by(TimeEntry.clock_in_at).all())

    # Group by cleaner, then by day, so the table reads the way a week does.
    days = [start + timedelta(days=i) for i in range(7)]
    rows = {}
    for e in entries:
        person = rows.setdefault(e.staff_id, {
            'staff': e.staff,
            'by_day': {d.isoformat(): 0.0 for d in days},
            'total': 0.0,
            'open': 0,
            'entries': [],
        })
        key = e.clock_in_at.date().isoformat()
        if e.is_open:
            person['open'] += 1
        if key in person['by_day']:
            person['by_day'][key] += e.hours
        person['total'] = round(person['total'] + e.hours, 2)
        person['entries'].append(e)

    ordered = sorted(rows.values(), key=lambda r: (r['staff'].name or '').lower())
    grand = round(sum(r['total'] for r in ordered), 2)
    day_totals = {d.isoformat(): round(sum(r['by_day'][d.isoformat()] for r in ordered), 2)
                  for d in days}

    return render_template('admin/timesheet.html',
                           rows=ordered, days=days, start=start, end=end,
                           grand=grand, day_totals=day_totals,
                           prev_start=(start - timedelta(days=7)).isoformat(),
                           next_start=(start + timedelta(days=7)).isoformat(),
                           today_iso=today.isoformat())


@contractors_bp.route('/payroll')
@owner_required
@requires_plan('payroll')
def payroll():
    today = date.today()
    # Default: this week (Mon-Sun)
    week_start_str = request.args.get('start', (today - timedelta(days=today.weekday())).isoformat())
    week_end_str = request.args.get('end', (today - timedelta(days=today.weekday()) + timedelta(days=6)).isoformat())

    jobs = Booking.query.filter(
        Booking.preferred_date >= week_start_str,
        Booking.preferred_date <= week_end_str,
        Booking.status == 'completed',
    ).all()

    staff_all = Staff.query.filter_by(is_active=True).order_by(Staff.name).all()
    staff_map = {s.name: s for s in staff_all}

    payroll_data = {}

    # How each already-paid job was settled — so the row can say "✅ Paid · Cash"
    # rather than leaving her guessing whether it went through Stripe.
    pay_ids = [b.cleaner_payment_id for b in jobs if b.cleaner_payment_id]
    pay_ids += [c.payment_id for b in jobs for c in b.crew if c.payment_id]
    methods = {p.id: p.method for p in
               ContractorPayment.query.filter(ContractorPayment.id.in_(pay_ids)).all()} \
        if pay_ids else {}

    def add_row(s, job, earned, paid, crew=None):
        row = payroll_data.setdefault(s.name, {'staff': s, 'jobs': [], 'total': 0, 'paid_total': 0})
        pid = crew.payment_id if crew else job.cleaner_payment_id
        row['jobs'].append({'booking': job, 'earned': earned, 'paid': paid, 'crew': crew,
                            'method': methods.get(pid), 'payment_id': pid})
        if paid:
            row['paid_total'] += earned
        else:
            row['total'] += earned          # 'total' = still owed (unpaid)

    for job in jobs:
        if job.crew:
            # Crew job — one payroll line per person, at the split the owner set.
            for c in job.crew:
                if c.staff:
                    add_row(c.staff, job, c.pay_amount or 0, bool(c.paid_at), crew=c)
            continue
        s = staff_map.get(job.assigned_cleaner or '')
        if not s:
            continue
        add_row(s, job, job.pay_for(s), bool(job.cleaner_paid_at))

    payroll_data = dict(sorted(payroll_data.items()))
    grand_total = sum(v['total'] for v in payroll_data.values())
    return render_template('admin/payroll.html',
        payroll=payroll_data, grand_total=round(grand_total, 2),
        week_start=week_start_str, week_end=week_end_str,
        stripe_configured=stripe_connect.is_configured(),
    )


@contractors_bp.route('/payroll/pay-job/<int:booking_id>', methods=['POST'])
@owner_required
def pay_job(booking_id):
    """Pay the assigned cleaner for ONE completed job — Stripe (default) or a
    recorded manual payment. Idempotent: a job already paid can't be paid again."""
    b = Booking.query.get_or_404(booking_id)
    back = redirect(url_for('contractors.payroll',
                            start=request.form.get('start', ''),
                            end=request.form.get('end', '')))

    if b.cleaner_paid_at:
        flash(f"That job was already paid on {b.cleaner_paid_at.strftime('%b %d, %Y')} — not paying again.", 'warning')
        return back

    name = (b.assigned_cleaner or '').strip()
    s = Staff.query.filter(db.func.lower(Staff.name) == name.lower()).first() if name else None
    if not s:
        flash('No matching team member for this job, so there is no one to pay.', 'error')
        return back

    earned = b.pay_for(s)
    if earned <= 0:
        flash(f'{s.name}\'s pay for this job comes to $0 — set the job\'s hours or price first.', 'warning')
        return back

    method = request.form.get('method', 'stripe')
    when = _paid_on(request.form.get('paid_on'), b)
    pay = _send_payout(s, b, earned, method, idem_key=f'payout-job-{b.id}', when=when,
                       tip=_typed_tip(request.form))
    if pay is None:
        return back
    b.cleaner_paid_at = when
    b.cleaner_payment_id = pay.id
    db.session.commit()
    return back


def _typed_tip(form):
    """The tip share SHE typed for this person on the payroll row.

    Nothing is calculated. Tips get divided between whoever was actually on the
    job — her, the cleaner, sometimes her daughter, who isn't in the CRM — so no
    rule could get it right. She knows the split; the CRM records it."""
    try:
        tip = float((form.get('tip') or '').strip() or 0)
    except ValueError:
        return 0.0
    return round(max(0.0, tip), 2)


def _paid_on(raw, booking=None):
    """When the money actually changed hands.

    Cash gets handed over on the day of the job, but she might not record it
    until days later — and the P&L sorts costs by this date, so stamping it with
    the click time drops the expense into the wrong month. Falls back to the
    job's own date, then to now."""
    for candidate in (raw, getattr(booking, 'preferred_date', None)):
        if candidate:
            try:
                return datetime.strptime(str(candidate)[:10], '%Y-%m-%d')
            except ValueError:
                continue
    return datetime.utcnow()


def _send_payout(s, b, earned, method, idem_key, when=None, tip=0.0):
    """Move (or record) one payout and return the saved ContractorPayment.
    Flashes and returns None if it couldn't go through. Caller stamps whatever
    it is that got paid — the booking for a solo job, the crew row for one
    member of a crew — and commits."""
    job_date = b.preferred_date or ''
    desc = f'{s.name} — {b.name or "job"} {job_date}'.strip()
    # The tip is the customer's money passing through — it goes out with the
    # payout but is recorded separately so it never counts as a business cost.
    tip = round(tip or 0, 2)
    total = round(earned + tip, 2)
    if tip:
        desc += f' (incl. ${tip:.2f} tip)'
    # A Stripe transfer happens now by definition; a recorded payment happened
    # whenever she says it did.
    when = datetime.utcnow() if method == 'stripe' else (when or datetime.utcnow())

    if method == 'stripe':
        _sync_stripe_status(s)
        if not (s.stripe_account_id and s.stripe_payouts_enabled):
            flash(f"{s.name} isn't set up for Stripe payouts yet — record a manual payment or send their onboarding link.", 'warning')
            return None
        ok, result = stripe_connect.create_transfer(
            s.stripe_account_id, total, description=desc,
            idempotency_key=idem_key)   # the same share can never transfer twice
        if not ok:
            flash(f'Stripe payment failed: {result}', 'error')
            return None
        pay = ContractorPayment(staff_id=s.id, booking_id=b.id, amount=earned,
                                tip_amount=tip, method='stripe', status='paid',
                                stripe_transfer_id=result, note=desc, created_at=when)
    else:
        # Manual: Venmo / Zelle / cash / check — recorded, not moved by us.
        pay = ContractorPayment(staff_id=s.id, booking_id=b.id, amount=earned,
                                tip_amount=tip, method=method, status='paid',
                                note=desc, created_at=when)

    db.session.add(pay)
    db.session.flush()                     # get pay.id
    if method == 'stripe':
        flash(f'✅ Sent ${total:.2f} to {s.name} via Stripe for the {job_date} job'
              + (f' (${earned:.2f} pay + ${tip:.2f} tip).' if tip else '.'), 'success')
    else:
        flash(f'Recorded ${total:.2f} paid to {s.name} via {method.title()} for the {job_date} job'
              + (f' (${earned:.2f} pay + ${tip:.2f} tip)' if tip else '')
              + f' — dated {when.strftime("%b %-d, %Y")}.', 'success')
    return pay


@contractors_bp.route('/payroll/pay-crew/<int:crew_id>', methods=['POST'])
@owner_required
def pay_crew(crew_id):
    """Pay ONE cleaner their share of a crew job. Each share is paid separately,
    so paying Maria never touches what Ana is owed on the same house."""
    c = BookingCrew.query.get_or_404(crew_id)
    back = redirect(url_for('contractors.payroll',
                            start=request.form.get('start', ''),
                            end=request.form.get('end', '')))

    if c.paid_at:
        flash(f"That share was already paid on {c.paid_at.strftime('%b %d, %Y')} — not paying again.", 'warning')
        return back
    if not c.staff:
        flash('No team member on that crew spot, so there is no one to pay.', 'error')
        return back

    earned = c.pay_amount or 0
    if earned <= 0:
        flash(f"{c.staff.name}'s share is $0 — set their split on the booking first.", 'warning')
        return back

    when = _paid_on(request.form.get('paid_on'), c.booking)
    pay = _send_payout(c.staff, c.booking, earned, request.form.get('method', 'stripe'),
                       idem_key=f'payout-crew-{c.id}', when=when,
                       tip=_typed_tip(request.form))
    if pay is None:
        return back
    c.paid_at = pay.created_at
    c.payment_id = pay.id
    db.session.commit()
    return back


@contractors_bp.route('/payroll/payment-date/<int:payment_id>', methods=['POST'])
@owner_required
def fix_payment_date(payment_id):
    """Correct the date on a payment that's already recorded.

    The P&L sorts costs by this date, so a payment logged a few days late lands
    in the wrong month and makes both months wrong. This moves it, and keeps the
    booking's and crew row's stamps in step so nothing drifts apart."""
    pay = ContractorPayment.query.get_or_404(payment_id)
    back = redirect(url_for('contractors.payroll',
                            start=request.form.get('start', ''),
                            end=request.form.get('end', '')))
    raw = (request.form.get('paid_on') or '').strip()
    try:
        when = datetime.strptime(raw[:10], '%Y-%m-%d')
    except ValueError:
        flash('Enter the date as a real calendar date.', 'error')
        return back

    was = pay.created_at
    pay.created_at = when
    # Keep every stamp that points at this payment in agreement.
    Booking.query.filter_by(cleaner_payment_id=pay.id).update({'cleaner_paid_at': when})
    BookingCrew.query.filter_by(payment_id=pay.id).update({'paid_at': when})
    db.session.commit()

    moved = was and was.strftime('%b %Y') != when.strftime('%b %Y')
    flash(f'Payment re-dated to {when.strftime("%b %-d, %Y")}.'
          + (f' It now counts in {when.strftime("%B")}, not {was.strftime("%B")}.' if moved else ''),
          'success')
    return back


@contractors_bp.route('/payroll/statement/<int:staff_id>')
@login_required
def pay_statement(staff_id):
    """Printable pay statement for one cleaner over a date range (Save as PDF)."""
    s = Staff.query.get_or_404(staff_id)
    today = date.today()
    start = request.args.get('start', (today - timedelta(days=today.weekday())).isoformat())
    end = request.args.get('end', (today - timedelta(days=today.weekday()) + timedelta(days=6)).isoformat())
    # Solo jobs plus crew jobs they worked — on a crew job they're only owed
    # their own share, not the whole job.
    jobs = Booking.query.outerjoin(BookingCrew, BookingCrew.booking_id == Booking.id).filter(
        db.or_(db.func.lower(Booking.assigned_cleaner) == (s.name or '').lower(),
               BookingCrew.staff_id == s.id),
        Booking.status == 'completed',
        Booking.preferred_date >= start,
        Booking.preferred_date <= end,
    ).distinct().order_by(Booking.preferred_date).all()
    rows, total = [], 0.0
    for j in jobs:
        if j.crew and not j.crew_row_for(s):
            continue          # crew job they aren't actually on (they're just the stale lead)
        earned = j.pay_for(s)
        total += earned
        rows.append({'booking': j, 'earned': earned})
    biz = branding.biz_name()
    return render_template('admin/pay_statement.html', s=s, rows=rows,
                           total=round(total, 2), start=start, end=end, biz=biz)


# ── Public application form ────────────────────────────────────────────────────

@contractors_bp.route('/apply', methods=['GET', 'POST'])
def apply():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()

        # ── Duplicate guard ────────────────────────────────────────────────────
        # If this email already applied, UPDATE that card instead of creating a
        # new one. Prevents the same person showing up multiple times, and skips
        # re-sending the notify/interview emails.
        existing = None
        if email:
            existing = ContractorApplication.query.filter(
                db.func.lower(ContractorApplication.email) == email.lower()
            ).order_by(ContractorApplication.created_at.desc()).first()
        if existing:
            existing.name = name or existing.name
            existing.phone = request.form.get('phone', '').strip() or existing.phone
            existing.years_experience = request.form.get('years_experience', '') or existing.years_experience
            existing.services = ', '.join(request.form.getlist('services')) or existing.services
            existing.availability = ', '.join(request.form.getlist('availability')) or existing.availability
            existing.has_transportation = 'has_transportation' in request.form
            existing.has_supplies = 'has_supplies' in request.form
            existing.has_references = 'has_references' in request.form
            existing.background_check_consent = 'background_check_consent' in request.form
            existing.agrees_to_ic_terms = 'agrees_to_ic_terms' in request.form
            existing.why_interested = request.form.get('why_interested', '').strip() or existing.why_interested
            _note = f"Re-applied {datetime.utcnow().strftime('%b %d, %Y')} — info updated, no duplicate created."
            existing.admin_notes = (existing.admin_notes + "\n" + _note) if existing.admin_notes else _note
            db.session.commit()
            return render_template('public/apply_done.html', name=existing.name)

        a = ContractorApplication(
            name=name,
            email=email,
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
        notify = branding.owner_email()
        send_email(
            to_email=notify, to_name=branding.biz_name(),
            from_name=f'{branding.biz_name()} Hiring',
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
    biz = branding.biz_name()
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

        # Alert the owner that this contractor signed
        _notify_owner(
            f'✍️ {s.name} signed their agreement',
            f'<div style="font-family:Inter,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1f1333">'
            f'<h2 style="color:#b98a33">{s.name} signed their agreement ✍️</h2>'
            f'<p>Signed as "<strong>{typed_name}</strong>" on {s.agreement_signed_at.strftime("%b %d, %Y")}. '
            f'Check their onboarding progress on their Team profile.</p></div>')

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
    biz = branding.biz_name()
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
    biz = branding.biz_name()

    if s.welcome_forms_at:
        return render_template('public/onboarding_forms_done.html', s=s, biz=biz, already_done=True)

    if request.method == 'POST':
        s.emergency_contact_name = request.form.get('emergency_contact_name', '').strip() or s.emergency_contact_name
        s.emergency_contact_phone = request.form.get('emergency_contact_phone', '').strip() or s.emergency_contact_phone
        s.welcome_forms_at = datetime.utcnow()
        # Mark only the forms step done. Payment (payment_info) is marked complete
        # by _sync_stripe_status when Stripe payouts actually go live — not here —
        # and uniform_size is employee-only, so contractors never get it.
        steps = s.get_onboarding()
        if 'welcome_forms' not in steps:
            steps.append('welcome_forms')
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
    biz = branding.biz_name()
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
    biz = branding.biz_name()
    reasons_html_en = ''.join(f'<li style="margin-bottom:6px">{r}</li>' for r in reasons_en)
    reasons_html_es = ''.join(f'<li style="margin-bottom:6px">{r}</li>' for r in reasons_es)
    html = f"""
<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;background:#f6f5fb">
  <div style="background:#1f1333;padding:24px;border-radius:12px 12px 0 0;text-align:center">
    <h1 style="color:#d3a84f;font-family:Georgia,serif;margin:0;font-size:1.6rem">{branding.biz_name()}</h1>
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
        _now = datetime.utcnow()
        app_rec.interview_status = 'sent'
        app_rec.interview_sent_at = _now
        app_rec.interview_last_sent_at = _now
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
You are paid a flat, fixed amount for each job, agreed before you accept it. Every job offer states the property and the exact dollar amount you will be paid for completing that job. You are not paid by the hour, and your pay is not a share or percentage of what the client is charged.

The amount offered reflects the size, condition and service requested for that property. It does not change according to how long the job takes you, and it does not change if the client is given a discount. If a property turns out to be materially different from what the offer described, stop and contact the Company before continuing, and a revised amount will be agreed.

You decide whether each amount is worth your time before you accept the job. Declining a job is not a breach of this agreement.

Payment is issued after each job is marked complete — by default, the same day. If you prefer, you may choose weekly payment during onboarding to be paid once per week instead.

4. INSURANCE
As an independent contractor, you operate your own cleaning business and are responsible for carrying your own general liability insurance. The Company's insurance covers the Company and does not extend to independent contractors. Affordable coverage is widely available (often around $30–$50 per month), and the Company is glad to share provider options. While it is not required to begin working, we strongly recommend obtaining coverage to protect both you and the clients you serve.

5. SCHEDULING
Jobs will be offered to you based on availability. You may accept or decline jobs, but consistent availability is expected. Last-minute cancellations must be communicated immediately.

6. CONDUCT & QUALITY
You agree to: arrive on time, maintain professional appearance and communication, follow all cleaning checklists, treat client homes and belongings with the utmost care, and never solicit clients directly.

7. CONFIDENTIALITY
You agree to keep all client information, pricing, and business processes strictly confidential, both during and after this agreement.

8. OUR CLIENTS & NON-SOLICITATION
The clients you serve belong to {biz_name}. You are introduced to them through the Company's advertising, reputation, and booking systems — not on your own. During this agreement and for 24 months after it ends, you agree that you will NOT, directly or indirectly:
- Solicit, divert, or accept cleaning work from any {biz_name} client you met or served through the Company;
- Offer a {biz_name} client your own services, side jobs, or lower "off-the-books" pricing;
- Encourage or help any client leave {biz_name}.
Going into a client's home and trying to take their business is a serious breach of trust and of this agreement.

9. NON-CIRCUMVENTION & BUYOUT FEE
If a client and contractor genuinely wish to work together directly, it may happen ONLY with the Company's written approval and payment of a buyout fee of $2,000 per client to {biz_name}. Because the true value of a lost client relationship is difficult to calculate exactly, this amount is agreed in advance as a fair and reasonable estimate of the Company's loss (liquidated damages, not a penalty). Working around the Company without this approval and fee is a breach of this agreement, and the Company may recover the buyout fee plus its collection costs and reasonable attorney's fees.

10. TERMINATION
Either party may terminate this agreement at any time, with or without cause. The confidentiality, non-solicitation, non-circumvention, and buyout terms above survive and remain in effect after this agreement ends.

ACKNOWLEDGMENT
By signing below, you confirm that you have read and understood this Agreement and agree to its terms as an independent contractor."""
