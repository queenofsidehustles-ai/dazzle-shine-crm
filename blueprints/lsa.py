"""Google Local Services Ads leads — import, match, and follow up.

Routes only. The matching and the sequence itself live in lsa.py, so the cron
job and these screens are provably doing the same thing.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session)
from auth import login_required
from extensions import db
from models import LsaLead
import lsa

lsa_bp = Blueprint('lsa', __name__, url_prefix='/leads/lsa')


@lsa_bp.route('/')
@login_required
def index():
    view = request.args.get('view', 'not_booked')

    # Re-match on every load. It is a couple of in-memory dictionary lookups,
    # and the alternative is a screen that confidently shows someone as never
    # having booked twenty minutes after they booked.
    everything = LsaLead.query.order_by(LsaLead.received_at.desc().nullslast()).all()
    if everything:
        lsa.match_bookings(everything)

    from notifications import sms_opted_out
    opted_out = {l.phone for l in everything if sms_opted_out(l.phone)}

    counts = {
        'all': len(everything),
        'booked': sum(1 for l in everything if l.booked),
        'not_booked': sum(1 for l in everything if not l.booked),
        'in_sequence': sum(1 for l in everything if l.in_sequence),
    }
    if view == 'booked':
        rows = [l for l in everything if l.booked]
    elif view == 'in_sequence':
        rows = [l for l in everything if l.in_sequence]
    elif view == 'all':
        rows = everything
    else:
        rows = [l for l in everything if not l.booked]

    return render_template('admin/lsa_leads.html', rows=rows, counts=counts,
                           view=view, opted_out=opted_out,
                           due_count=len(lsa.due_now()))


@lsa_bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_csv():
    """Upload the CSV straight off the LSA Leads page (the DOWNLOAD button)."""
    if request.method == 'GET':
        return render_template('admin/lsa_import.html')

    f = request.files.get('file')
    if not f or not f.filename:
        flash('Choose the CSV you downloaded from Local Services Ads first.', 'warning')
        return redirect(url_for('lsa.import_csv'))

    rows, problems = lsa.parse_csv(f.read())
    if not rows:
        for p in problems[:5]:
            flash(p, 'warning')
        if not problems:
            flash('No leads found in that file.', 'warning')
        return redirect(url_for('lsa.import_csv'))

    added, updated = lsa.import_rows(rows)
    booked = lsa.match_bookings()
    flash(f'Imported {added} new lead{"s" if added != 1 else ""}'
          f'{f", refreshed {updated}" if updated else ""}. '
          f'{booked} of them already booked with you.', 'success')
    # Problems are shown but never block: a handful of unusable rows should not
    # cost her the hundred that were fine.
    for p in problems[:5]:
        flash(p, 'warning')
    if len(problems) > 5:
        flash(f'…and {len(problems) - 5} more rows skipped.', 'warning')
    return redirect(url_for('lsa.index'))


@lsa_bp.route('/<int:lead_id>/start', methods=['POST'])
@login_required
def start(lead_id):
    lead = LsaLead.query.get_or_404(lead_id)
    from notifications import sms_opted_out
    if lead.booked:
        flash(f'{lead.pretty_phone} has booked with you — leaving them alone.', 'warning')
    elif sms_opted_out(lead.phone):
        flash(f'{lead.pretty_phone} has asked us to stop texting.', 'warning')
    elif lsa.start_sequence(lead):
        flash(f'{lead.pretty_phone} added — the first text goes out on the next run.',
              'success')
    else:
        flash(f'{lead.pretty_phone} is already in the sequence.', 'warning')
    return redirect(request.referrer or url_for('lsa.index'))


@lsa_bp.route('/<int:lead_id>/quote', methods=['GET', 'POST'])
@login_required
def quote(lead_id):
    """Take a caller's details and email them the price you gave them.

    This is the gap the CRM had: the quote email only ever fired from the
    website form, so somebody who rang up and asked what a clean would cost got
    nothing unless it was written out by hand."""
    lead = LsaLead.query.get_or_404(lead_id)
    import quoting
    from models import Lead

    existing = Lead.query.get(lead.crm_lead_id) if lead.crm_lead_id else None

    if request.method == 'POST':
        crm_lead, err = quoting.handle_quote_form(request.form, lsa_lead=lead)
        if err:
            flash(err, 'warning')
            return redirect(url_for('lsa.quote', lead_id=lead_id))
        quoting.link_lsa_caller(crm_lead, lead)
        ok, detail = quoting.send_quote(crm_lead)
        if ok:
            flash(f'Quote for ${crm_lead.quoted_price:.2f} emailed to '
                  f'{crm_lead.email} 📩 Follow-up emails will go out if they '
                  f'don\'t book.', 'success')
            return redirect(url_for('lsa.index'))
        flash(f'⚠️ Could not send the quote: {detail}', 'warning')
        return redirect(url_for('lsa.quote', lead_id=lead_id))

    return render_template('admin/lsa_quote.html', lead=lead, existing=existing,
                           **quoting.form_context(existing))


@lsa_bp.route('/<int:lead_id>/track', methods=['POST'])
@login_required
def set_track(lead_id):
    """Correct which conversation a lead belongs in.

    Google's billing status is a good guess and nothing more. She was on the
    calls, so when the two disagree she wins — and import_rows leaves a track
    alone once it has been set, so this survives the next import."""
    lead = LsaLead.query.get_or_404(lead_id)
    want = request.form.get('track', '')
    if want not in (lsa.MISSED, lsa.QUOTED):
        flash('Unknown follow-up track.', 'warning')
        return redirect(request.referrer or url_for('lsa.index'))
    lead.track = want
    db.session.commit()
    label = dict(lsa.TRACKS)[want]
    flash(f'{lead.pretty_phone} moved to “{label}”.', 'success')
    return redirect(request.referrer or url_for('lsa.index'))


@lsa_bp.route('/<int:lead_id>/stop', methods=['POST'])
@login_required
def stop(lead_id):
    lead = LsaLead.query.get_or_404(lead_id)
    lsa.stop_sequence(lead, 'manual')
    flash(f'Stopped following up with {lead.pretty_phone}.', 'success')
    return redirect(request.referrer or url_for('lsa.index'))


@lsa_bp.route('/start-all', methods=['POST'])
@login_required
def start_all():
    """Put every un-booked, un-opted-out lead into the sequence.

    Confirmed on the page before it gets here, because this is the one action
    on the screen that reaches a lot of real phones at once."""
    from notifications import sms_opted_out
    started = 0
    for lead in LsaLead.query.filter_by(booked=False).all():
        if sms_opted_out(lead.phone) or lead.seq_started_at:
            continue
        if lsa.start_sequence(lead):
            started += 1
    flash(f'{started} lead{"s" if started != 1 else ""} added to the follow-up '
          f'sequence. Nothing sends until the next run — use Preview first if '
          f'you want to see the wording.', 'success')
    return redirect(url_for('lsa.index'))


@lsa_bp.route('/preview')
@login_required
def preview():
    """Exactly what the next run would send, to whom, word for word."""
    due = lsa.due_now()
    items = [{'lead': l, 'step': (l.seq_step or 0) + 1,
              'track': dict(lsa.TRACKS)[l.track or lsa.QUOTED],
              'body': lsa.message_for((l.seq_step or 0) + 1, l)} for l in due]
    samples = [{'track': track, 'label': label,
                'bodies': [lsa.message_for(n, _Sample(track)) for n in (1, 2, 3)]}
               for track, label in lsa.TRACKS]
    return render_template('admin/lsa_preview.html', items=items, samples=samples,
                           days=[d for d, _n in lsa.SEQUENCE])


class _Sample:
    """Stand-in lead so both sets can be read before anyone is in a sequence."""
    received_at = None
    phone = '4070000000'

    def __init__(self, track):
        self.track = track
