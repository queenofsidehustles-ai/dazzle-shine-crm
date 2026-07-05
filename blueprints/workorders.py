import json
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from models import Booking, ChecklistTemplate, JobChecklist, Staff
from extensions import db
from notifications import send_email, send_sms

workorders_bp = Blueprint('workorders', __name__, url_prefix='/workorders')

DEFAULT_ITEMS = {
    'standard': [
        'Dust all surfaces and furniture', 'Vacuum all carpets and rugs',
        'Mop all hard floors', 'Clean and disinfect bathrooms (toilet, sink, shower/tub, mirror)',
        'Clean kitchen (counters, sink, stovetop exterior, microwave exterior)',
        'Wipe door handles and light switches', 'Empty all trash cans',
        'Straighten and tidy all rooms',
    ],
    'deep': [
        'All standard clean tasks', 'Clean inside microwave', 'Wipe all cabinet fronts',
        'Clean baseboards', 'Dust ceiling fans and light fixtures',
        'Clean window sills and ledges', 'Scrub bathroom grout',
        'Clean behind and under appliances', 'Wipe all walls and doors',
    ],
    'moveout': [
        'All deep clean tasks', 'Clean inside all cabinets and drawers',
        'Clean inside oven', 'Clean inside refrigerator', 'Clean inside dishwasher',
        'Clean all closets', 'Remove all remaining debris',
        'Final walkthrough — document condition with photos',
    ],
    'airbnb': [
        'Strip all beds — bag used linens', 'Make all beds with fresh linens',
        'Replace towels in all bathrooms', 'Restock toilet paper, soap, shampoo, conditioner',
        'Check for and remove any guest belongings', 'Report any damage or missing items',
        'All standard clean tasks', 'Stage bathroom and kitchen for next guest',
    ],
    'apartment': [
        'Dust all surfaces and furniture', 'Vacuum all carpets and rugs',
        'Mop all hard floors', 'Clean bathrooms thoroughly',
        'Clean kitchen (counters, sink, stovetop, microwave exterior)',
        'Wipe door handles and light switches', 'Empty all trash cans',
    ],
    'luxury': [
        'White-glove dust all surfaces including art and decor',
        'Vacuum with HEPA filter — all rugs and carpets', 'Hand-mop all hard floors',
        'Deep clean all bathrooms', 'Polish all fixtures',
        'Clean kitchen including all appliance exteriors', 'Clean interior windows',
        'Wipe all baseboards and crown molding', 'Straighten and stage all rooms',
    ],
}


@workorders_bp.route('/templates')
@login_required
def templates():
    all_templates = ChecklistTemplate.query.order_by(ChecklistTemplate.name).all()
    return render_template('admin/checklists.html', templates=all_templates)


@workorders_bp.route('/templates/new', methods=['GET', 'POST'])
@login_required
def new_template():
    if request.method == 'POST':
        items = [i.strip() for i in request.form.get('items', '').split('\n') if i.strip()]
        t = ChecklistTemplate(
            name=request.form['name'].strip(),
            service_type=request.form.get('service_type', ''),
            items=json.dumps(items),
        )
        db.session.add(t)
        db.session.commit()
        flash('Checklist template saved!', 'success')
        return redirect(url_for('workorders.templates'))
    svc = request.args.get('service_type', 'standard')
    defaults = '\n'.join(DEFAULT_ITEMS.get(svc, DEFAULT_ITEMS['standard']))
    return render_template('admin/checklist_form.html', template=None, default_items=defaults)


@workorders_bp.route('/templates/<int:template_id>', methods=['GET', 'POST'])
@login_required
def edit_template(template_id):
    t = ChecklistTemplate.query.get_or_404(template_id)
    if request.method == 'POST':
        items = [i.strip() for i in request.form.get('items', '').split('\n') if i.strip()]
        t.name = request.form['name'].strip()
        t.service_type = request.form.get('service_type', '')
        t.items = json.dumps(items)
        db.session.commit()
        flash('Template updated!', 'success')
        return redirect(url_for('workorders.templates'))
    return render_template('admin/checklist_form.html', template=t,
                           default_items='\n'.join(t.get_items()))


@workorders_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
def delete_template(template_id):
    t = ChecklistTemplate.query.get_or_404(template_id)
    db.session.delete(t)
    db.session.commit()
    flash('Template deleted.', 'success')
    return redirect(url_for('workorders.templates'))


def create_and_send_workorder(booking, template_id=None):
    """Create a job checklist for a booking and email/text it to the assigned
    cleaner. Reusable from the manual route AND the auto-assign hook.
    Returns True if a checklist was created."""
    if template_id:
        tmpl = ChecklistTemplate.query.get(template_id)
        items = tmpl.get_items() if tmpl else DEFAULT_ITEMS.get(booking.service_type, DEFAULT_ITEMS['standard'])
        template_name = tmpl.name if tmpl else booking.service_label
    else:
        items = DEFAULT_ITEMS.get(booking.service_type, DEFAULT_ITEMS['standard'])
        template_name = booking.service_label

    token = secrets.token_urlsafe(32)
    checklist = JobChecklist(booking_id=booking.id, template_name=template_name,
                              items=json.dumps(items), token=token)
    db.session.add(checklist)
    db.session.commit()

    cleaner_email, cleaner_phone = None, None
    if booking.assigned_cleaner:
        cleaner = Staff.query.filter_by(name=booking.assigned_cleaner, is_active=True).first()
        if cleaner:
            cleaner_email = cleaner.email
            cleaner_phone = cleaner.phone

    checklist_url = url_for('workorders.view_checklist', token=token, _external=True, _scheme='https')
    sop_url = url_for('sops.library', _external=True, _scheme='https')
    date_text = booking.preferred_date or 'TBD'
    time_text = booking.preferred_time or 'TBD'
    extras_html = f"<p><strong>Add-ons:</strong> {booking.extras}</p>" if booking.extras else ''
    notes_html = f"<p><strong>Notes:</strong> {booking.internal_notes or booking.notes}</p>" if (booking.internal_notes or booking.notes) else ''

    if cleaner_email:
        send_email(
            to_email=cleaner_email, to_name=booking.assigned_cleaner or 'Team',
            subject=f'Work Order: {booking.name} — {date_text} at {time_text}',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Work Order — {date_text}</h2>
  <p><strong>Client:</strong> {booking.name} &nbsp; <a href="tel:{booking.phone}">{booking.phone}</a></p>
  <p><strong>Address:</strong> {booking.address}, {booking.city} {booking.zip_code}</p>
  <p><strong>Service:</strong> {booking.service_label} &nbsp; <strong>Time:</strong> {time_text}</p>
  <p><strong>Bedrooms:</strong> {booking.bedrooms} &nbsp; <strong>Bathrooms:</strong> {booking.bathrooms}</p>
  {extras_html}{notes_html}
  <hr style="border:none;border-top:1px solid #e4dfef;margin:20px 0"/>
  <p><a href="{checklist_url}" style="background:#d3a84f;color:#1a1225;padding:12px 24px;border-radius:999px;text-decoration:none;font-weight:700">Open Job Checklist →</a></p>
  <p style="font-size:0.82rem;color:#9a95ad">Check off each item as you complete it. Need a refresher? <a href="{sop_url}" style="color:#b98a33">See our cleaning SOPs →</a></p>
</div>""",
        )

    if cleaner_phone:
        send_sms(cleaner_phone,
                 f"Work Order: {booking.name} · {booking.address} · {date_text} at {time_text}. "
                 f"Checklist: {checklist_url}")
    return True


@workorders_bp.route('/send/<int:booking_id>', methods=['POST'])
@login_required
def send_workorder(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    create_and_send_workorder(booking, request.form.get('template_id'))
    flash('Work order sent to cleaner!', 'success')
    return redirect(url_for('bookings.detail', booking_id=booking_id))


# ── Public checklist (no login needed) ────────────────────────────────────────

@workorders_bp.route('/checklist/<token>')
def view_checklist(token):
    import os
    checklist = JobChecklist.query.filter_by(token=token).first_or_404()
    return render_template('public/checklist.html', checklist=checklist,
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'dasgvqtyk'),
        upload_preset=os.environ.get('CLOUDINARY_UPLOAD_PRESET', 'dazzle_interviews'),
    )


@workorders_bp.route('/checklist/<token>/add-photo', methods=['POST'])
def add_photo(token):
    checklist = JobChecklist.query.filter_by(token=token).first_or_404()
    data = request.get_json() or {}
    phase = data.get('phase')          # 'before' or 'after'
    url = (data.get('url') or '').strip()
    if phase not in ('before', 'after') or not url:
        return jsonify({'ok': False, 'error': 'Missing phase or url'}), 400
    if phase == 'before':
        photos = checklist.get_before_photos()
        photos.append(url)
        checklist.before_photos = json.dumps(photos)
    else:
        photos = checklist.get_after_photos()
        photos.append(url)
        checklist.after_photos = json.dumps(photos)
    db.session.commit()
    return jsonify({'ok': True})


@workorders_bp.route('/checklist/<token>/submit-complete', methods=['POST'])
def submit_complete(token):
    import os
    checklist = JobChecklist.query.filter_by(token=token).first_or_404()
    before = checklist.get_before_photos()
    after = checklist.get_after_photos()
    if not before or not after:
        return jsonify({'ok': False,
            'error': 'Please add at least one BEFORE photo and one AFTER photo.'}), 400

    checklist.photos_submitted_at = datetime.utcnow()
    if not checklist.completed_at:
        checklist.completed_at = datetime.utcnow()
    booking = checklist.booking
    if booking and booking.status not in ('cancelled',):
        booking.status = 'completed'
    db.session.commit()

    # Notify the owner that the job is closed out and ready for payment review
    booking = checklist.booking
    owner_email = os.environ.get('NOTIFY_EMAIL') or os.environ.get('OWNER_EMAIL', 'dazzleandshinemaids@gmail.com')
    try:
        review_url = url_for('bookings.detail', booking_id=booking.id, _external=True, _scheme='https')
        send_email(
            to_email=owner_email, to_name='Dazzle & Shine Maids',
            subject=f'Job completed — {booking.name} ({len(before)} before / {len(after)} after photos)',
            html=f"""
<div style="font-family:Inter,sans-serif;max-width:560px;margin:0 auto;color:#1f1333">
  <h2 style="color:#b98a33">Job Closed Out — Ready for Payment Review</h2>
  <p><strong>{booking.assigned_cleaner or 'Cleaner'}</strong> finished the job for
     <strong>{booking.name}</strong> and submitted photos.</p>
  <p>📸 {len(before)} before photo(s) · {len(after)} after photo(s)</p>
  <p><a href="{review_url}" style="background:#d3a84f;color:#1a1225;padding:12px 24px;border-radius:999px;text-decoration:none;font-weight:700">Review Photos &amp; Release Payment →</a></p>
</div>""",
        )
    except Exception:
        pass

    # Text the owner too (works once Twilio is connected)
    owner_phone = os.environ.get('OWNER_PHONE', '')
    if owner_phone:
        send_sms(owner_phone,
                 f"✅ Job done: {booking.assigned_cleaner or 'Cleaner'} finished {booking.name}'s "
                 f"cleaning and submitted {len(before)} before + {len(after)} after photos. "
                 f"Review to release payment.")

    return jsonify({'ok': True})


@workorders_bp.route('/checklist/<token>/check', methods=['POST'])
def toggle_check(token):
    checklist = JobChecklist.query.filter_by(token=token).first_or_404()
    idx = request.json.get('index')
    completed = checklist.get_completed()
    if idx in completed:
        completed.discard(idx)
    else:
        completed.add(idx)
    checklist.completed_items = json.dumps(list(completed))
    all_done = len(completed) >= len(checklist.get_items())
    checklist.completed_at = datetime.utcnow() if all_done else None
    db.session.commit()
    return jsonify({'ok': True, 'percent': checklist.completion_percent, 'all_done': all_done})
