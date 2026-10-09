"""The prospecting funnel — find businesses, call them, and keep every one of
them moving.

Search and import come from places_finder.py (the Google Places wrapper). What
happens after a call — the stage, the next action and the date it is due —
lives in prospecting.py. This module is the routes joining the two.

The default view is Today rather than everything ever imported, because a call
list that shows all two hundred rows in import order answers a question nobody
asked."""
import csv
import io
import json
from datetime import datetime, timedelta
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, Response)
import entitlements
from entitlements import requires_plan
from auth import login_required
from extensions import db
from models import Prospect
import places_finder as finder
import prospecting
from scheduling import local_today

places_finder_bp = Blueprint('places_finder', __name__, url_prefix='/find-leads')

# How many calls one sitting offers before it says you are done. Not a cap on
# what anybody may do -- "keep going" is one click -- but a morning that ends.
DAILY_STINT = 20

CATEGORIES = ['property_manager', 'realtor', 'airbnb', 'apartment',
              'daycare', 'medical_office', 'restaurant', 'gym', 'church',
              'general_contractor', 'office', 'other']


# Which opening belongs to which kind of business. The scripts are filed by
# what part of a call they are for -- outbound, objection, closing -- and the
# vertical lives in the title, because one company's "cold call opening" is
# several scripts and they differ by who is picking up. The call sheet asked
# for a script category named 'office' and there has never been one, so the
# panel was empty on every call.
VERTICAL_HINTS = {
    'office':             ('office', 'daycare', 'medical'),
    'medical_office':     ('medical', 'office'),
    'daycare':            ('daycare', 'office'),
    'restaurant':         ('restaurant', 'office'),
    'gym':                ('gym', 'fitness', 'office'),
    'church':             ('church', 'office'),
    'apartment':          ('apartment', 'property manager'),
    'property_manager':   ('property manager', 'apartment'),
    'realtor':            ('realtor',),
    'airbnb':             ('airbnb', 'str ', 'turnover'),
    'general_contractor': ('office',),
}


def _pick_openings(outbound, category):
    """The openings worth reading before this particular call.

    Falls back to every opening rather than none: a script that is not quite
    for this business still beats a blank panel on a call that is about to
    start.
    """
    hints = VERTICAL_HINTS.get(category, ())
    matched = [s for s in outbound
               if any(h in (s.get('title') or '').lower() for h in hints)] if hints else []
    chosen = matched or outbound

    # The seeded "[Your Company]" versions sit beside the ones she has made
    # her own. Hers win; the generic is what is left when she has not written
    # one yet.
    named = [s for s in chosen if '[your company]' not in (s.get('title') or '').lower()]
    return named or chosen


def _openings_for(groups, category):
    """The opening to read for one kind of business.

    The "Load starter scripts" pack files openings by kind (call_office,
    call_medical...), and those are the ones written for this call. A company
    seeded at signup has them in 'outbound' instead, picked by title.
    """
    from models import Script
    mapped = groups.get(Script.script_category_for(category), [])
    return mapped or _pick_openings(groups.get('outbound', []), category)


def _openers():
    """{brand: {category: [opening scripts]}} for the call drawer."""
    return {brand_key: {c: _openings_for(groups, c) for c in CATEGORIES}
            for brand_key, groups in _call_scripts().items()}


def _scripts_for(prospect, brand_key):
    """Everything to say on this call, in the order a call goes.

    Returned as sections so each can be opened on its own. Twenty scripts in
    one list is a document; four headings is something you can use with a
    phone against your ear.
    """
    groups = _call_scripts().get(brand_key, {})
    general = groups.get('general', [])

    def titled(rows, *words):
        return [r for r in rows
                if any(w in (r.get('title') or '').lower() for w in words)]

    sections = [
        ('What to say', _openings_for(groups, prospect.category)),
        ('Getting past the gatekeeper', titled(general, 'gatekeeper')),
        ('If it goes to voicemail', titled(general, 'voicemail')),
        ('If they push back', groups.get('objection', [])),
        ('Booking the walkthrough', groups.get('closing', [])),
    ]
    return [(label, rows) for label, rows in sections if rows]


def _call_scripts():
    """Scripts for the call drawer, as {brand: {category: [scripts]}}.

    Rendered once per brand rather than once per prospect: the same script says
    a different company name and phone number depending on which side of the
    business is being called, and the drawer swaps them client-side so a call
    doesn't wait on a page load.
    """
    from models import Script
    import brands
    import call_scripts

    rows = Script.query.order_by(Script.sort_order, Script.id).all()
    out = {}
    for key in (brands.PRIMARY, brands.COMMERCIAL):
        vals = call_scripts.tokens(key)
        per_cat = {}
        for s in rows:
            per_cat.setdefault(s.category, []).append({
                'title': s.title,
                'content': call_scripts.render(s.content, vals),
            })
        out[key] = per_cat
    return out


def _status_counts():
    return {
        'all': Prospect.query.count(),
        'new': Prospect.query.filter_by(status='new').count(),
        'called': Prospect.query.filter_by(status='called').count(),
        'interested': Prospect.query.filter_by(status='interested').count(),
        'won': Prospect.query.filter_by(status='won').count(),
    }


def _backfilled():
    """Every prospect, with anything predating the funnel filled in.

    Done on read rather than in a migration because the app has no migration
    step that can run Python — and a prospect with no stage would otherwise sit
    invisible in a list that only shows what's due.
    """
    import brands
    rows = Prospect.query.all()
    touched = [prospecting.backfill(p) for p in list(rows)]
    touched += [brands.backfill(p, brands.brand_for_prospect) for p in list(rows)]
    if any(touched):
        db.session.commit()
    # Only the side of the business currently on screen. Done here rather than
    # in each view so Today, Pipeline and Contacts can't disagree about it.
    return brands.filter_rows(rows, brands.brand_for_prospect)


def _view_args(view, prospects, **extra):
    """Everything find_leads.html needs, whichever view is on screen."""
    from models import Script
    import brands
    live = [p for p in prospects if p.is_open]
    emails = _email_templates()
    left = entitlements.remaining('lead_searches_per_month')
    plan_now = entitlements.effective_plan()
    nxt = entitlements._next_plan()
    next_plan = None
    if nxt:
        next_plan = {
            'label': entitlements.PLANS[nxt]['label'],
            'searches': entitlements.PLANS[nxt]['limits'].get(
                'lead_searches_per_month') or 0,
        }
    args = dict(
        plan_limits=entitlements.PLANS[plan_now]['limits'],
        next_plan=next_plan,
        view=view,
        searches_left=left,
        # What the owner actually came for. Up to 20 a search, so it is a
        # ceiling and the wording says so.
        businesses_left=(None if left is None else left * 20),
        own_google_key=finder.own_key(),
        search_capped=False,
        prospects=prospects,
        results=None,
        counts=_status_counts(),
        due=prospecting.due_counts(prospects),
        stage_counts={key: sum(1 for p in prospects if (p.stage or 'new') == key)
                      for key, _ in Prospect.STAGE_LABELS},
        stages=Prospect.STAGE_LABELS,
        live_count=len(live),
        status_filter='',
        categories=CATEGORIES,
        category_labels=Prospect.CATEGORY_LABELS,
        status_labels=Prospect.STATUS_LABELS,
        quick_actions=prospecting.QUICK_ACTIONS,
        next_rules={k: {'action': v[1], 'days': v[2]}
                    for k, v in prospecting.RULES.items()},
        max_attempts=prospecting.MAX_ATTEMPTS,
        today=local_today().isoformat(),
        demo=not finder.api_key_present(),
        search_category='property_manager',
        search_location='',
        # The lens, if one is on; otherwise each result is filed by its kind
        # of business at import (import_selected).
        search_brand=brands.active(),
        scripts=_call_scripts(),
        email_templates=emails,
        # Titles are the same whichever brand renders them — only the name and
        # number inside the body differ — so the picker is built from one list.
        email_template_titles=[t['title'] for t in emails[brands.PRIMARY]],
        brand_lens=brands.active(),
        brand_choices=brands.lens_choices(),
        default_brand=brands.PRIMARY,
        script_map=Script.PROSPECT_CATEGORY_MAP,
        # The opening to read for each kind of business, picked the way the
        # call sheet picks it. The drawer looked them up by category names
        # ('call_office' and so on) that no script has ever been filed under,
        # so it said "No script loaded yet" above six loaded openings.
        openers=_openers(),
        script_always=Script.ALWAYS_SHOW,
        script_labels=dict(Script.CATEGORIES),
        # Quotes are an owner's page on a plan that has commercial work, so
        # the drawer only offers the button to someone it will open for.
        can_quote=_can_quote(),
        sms_stopped=_sms_stopped(prospects),
        commercial_categories=list(brands._COMMERCIAL_CATEGORIES),
        brand_primary=brands.PRIMARY,
        brand_commercial=brands.COMMERCIAL,
    )
    args.update(extra)
    return args


def _sms_stopped(prospects):
    """Ids of the leads whose number has replied STOP. One query for the page,
    not one per row."""
    from models import SmsOptOut
    try:
        stopped = {row.phone for row in SmsOptOut.query.all()}
    except Exception:
        return set()
    return {p.id for p in prospects if _phone10(p.phone) in stopped}


def _is_owner():
    from auth import is_owner_session
    try:
        return is_owner_session()
    except Exception:
        return False


def _can_quote():
    from auth import is_owner_session
    try:
        return is_owner_session() and entitlements.can('commercial')
    except Exception:
        return False


def _email_templates():
    """The outreach emails, ready for the drawer to pre-fill a message with.

    Subject comes off the first 'Subject:' line and the coaching note is
    dropped — useful while you're learning the script, not something to mail to
    a property manager.
    """
    from models import Script
    import brands
    import call_scripts

    rows = Script.query.filter_by(category='email_outreach') \
                       .order_by(Script.sort_order, Script.id).all()
    out = {}
    for key in (brands.PRIMARY, brands.COMMERCIAL):
        vals = call_scripts.tokens(key)
        items = []
        for s in rows:
            body = call_scripts.render(s.content, vals)
            subject = ''
            lines = []
            for line in body.split('\n'):
                if not subject and line.lower().startswith('subject:'):
                    subject = line.split(':', 1)[1].strip()
                    continue
                if line.strip().startswith('💡'):
                    continue
                lines.append(line)
            items.append({'title': s.title, 'subject': subject,
                          'body': '\n'.join(lines).strip()})
        out[key] = items
    return out


@places_finder_bp.route('/')
@login_required
@requires_plan('lead_finder')
def dashboard():
    """Today by default — what is due, not everything ever imported."""
    view = request.args.get('view', 'today')
    # 'pipeline' and 'contacts' were the same 64 businesses twice -- once
    # grouped by stage, once alphabetically. That is one screen with a filter,
    # not two screens, so they became 'everyone'. The old names still work:
    # they are in links, bookmarks and anything already open.
    view = {'pipeline': 'everyone', 'contacts': 'everyone'}.get(view, view)
    if view not in ('today', 'everyone', 'find', 'month', 'add'):
        view = 'today'
    stage_filter = (request.args.get('stage') or '').strip()
    rows = _backfilled()

    if view == 'today':
        # Prospect.is_due is the one definition of due, shared with the
        # dashboard count. It was written out longhand here, and a prospect
        # resting in nurture could never satisfy it however overdue it got.
        today = local_today().isoformat()
        shown = sorted([p for p in rows if p.is_due(today)],
                       key=prospecting.due_sort_key)
    elif view == 'everyone':
        pool = [p for p in rows if (p.stage or 'new') == stage_filter] \
            if stage_filter else rows
        shown = sorted(pool, key=lambda p: (p.business_name or '').lower())
    elif view == 'month':
        # The commercial month. Callbacks are not appointments -- they have no
        # time and take four minutes -- so they do not belong on the jobs
        # calendar. They do belong somewhere you can see a fortnight ahead and
        # notice that the week of the 14th has eleven of them in it.
        shown = sorted(rows, key=prospecting.due_sort_key)
    else:
        shown = sorted(rows, key=prospecting.due_sort_key)

    extra = {}
    if view == 'month':
        import calendar as cal_module
        from datetime import date as _date
        try:
            year = int(request.args.get('year', local_today().year))
            month = int(request.args.get('month', local_today().month))
            _date(year, month, 1)
        except (TypeError, ValueError):
            year, month = local_today().year, local_today().month
        stamp = f'{year}-{month:02d}'
        by_day = {}
        for p in rows:
            if (p.next_action_date or '').startswith(stamp):
                try:
                    by_day.setdefault(int(p.next_action_date.split('-')[2]), []).append(p)
                except (IndexError, ValueError):
                    pass
        for d in by_day:
            by_day[d].sort(key=lambda r: (r.business_name or '').lower())
        extra = dict(
            cal=cal_module.Calendar(firstweekday=6).monthdayscalendar(year, month),
            cal_year=year, cal_month=month,
            cal_month_name=cal_module.month_name[month],
            by_day=by_day,
            prev_year=(year if month > 1 else year - 1),
            prev_month=(month - 1 if month > 1 else 12),
            next_year=(year if month < 12 else year + 1),
            next_month=(month + 1 if month < 12 else 1),
        )

    return render_template('admin/find_leads.html',
                           **_view_args(view, rows, shown=shown,
                                        stage_filter=stage_filter, **extra))


@places_finder_bp.route('/search', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def search():
    import brands
    category = request.form.get('category', 'property_manager')
    # Which side of the business this batch is being hunted for. Carried
    # through to the import so it is recorded from the search rather than
    # reverse-engineered from the category afterwards.
    # ALL is kept, not turned into the residential brand: it means "file each
    # result by its kind of business", which import_selected does. Defaulting
    # it to residential filed every office and restaurant search as homes.
    picked_brand = brands.normalize_lens(request.form.get('brand'))
    location = request.form.get('location', '').strip()
    if not location:
        flash('Enter a city or area to search — a town and state.', 'error')
        return redirect(url_for('places_finder.dashboard'))

    demo = not finder.api_key_present()
    capped, count_it = finder.allowance()

    if capped:
        entitlements.record_denial('limit:lead_searches_per_month',
                                   path='/find-leads/search')
        rows = _backfilled()
        return render_template('admin/find_leads.html',
                               **_view_args('find', rows,
                                            shown=sorted(rows, key=prospecting.due_sort_key),
                                            search_capped=True,
                                            search_category=category,
                                            search_brand=picked_brand,
                                            search_location=location))

    if demo:
        results, error = finder.demo_listings(category, location), ''
    else:
        ok, results, error = finder.search_businesses(category, location)
        if ok and count_it:
            # Counted after the call, because Google bills for the call. A
            # search that never reached them is not one of hers.
            entitlements.record_lead_search()
        if not ok:
            flash(f'Search failed: {error}', 'error')
            results = []

    # Flag which results are already in the call list (so we don't double-add).
    existing_ids = {p.place_id for p in Prospect.query.with_entities(Prospect.place_id).all()}
    for r in results:
        r['already'] = r['place_id'] in existing_ids
        r['category'] = category

    rows = _backfilled()
    return render_template('admin/find_leads.html',
                           **_view_args('find', rows,
                                        shown=sorted(rows, key=prospecting.due_sort_key),
                                        results=results, demo=demo,
                                        demo_reason=finder.demo_reason(),
                                        search_category=category,
                                        search_brand=picked_brand,
                                        search_location=location))


@places_finder_bp.route('/call')
@places_finder_bp.route('/call/<int:prospect_id>')
@login_required
@requires_plan('lead_finder')
def call_sheet(prospect_id=None):
    """One business at a time, with the script on the page and nothing else.

    The list view answers "who is there"; this answers "who am I ringing now".
    Those are different jobs and the list was doing both badly -- the script
    lived in a side drawer, the fields in another, and nothing carried you from
    one call to the next, so a morning's calling was a morning of navigating.

    Most calls end without a conversation, so the screen opens with three
    buttons and no form. Two of them are one click and the next business
    loads. Only "Spoke to someone" asks for anything, because only then is
    there anything to write down.
    """
    today = local_today().isoformat()
    rows = _backfilled()
    queue = sorted([p for p in rows if p.is_due(today)],
                   key=prospecting.due_sort_key)
    done = sum(1 for p in rows
               if p.called_at and p.called_at.date().isoformat() == today)

    # A sitting worth of calls, then a finish line. An endless queue is how a
    # backlog becomes a screen nobody opens: there is no version of today where
    # you get to the bottom, so there is no reason to start. Twenty is a
    # morning. Anybody who wants to keep going says so.
    stint_over = (done >= DAILY_STINT
                  and not prospect_id
                  and request.args.get('more') != '1')

    current = Prospect.query.get_or_404(prospect_id) if prospect_id else (
        None if stint_over else (queue[0] if queue else None))

    scripts, emails, can_email = [], [], False
    if current is not None:
        import brands
        # The stored brand first: the toggle on this page sets it, and the
        # opener has to read out the same company the quote button is for.
        key = brands.normalize(current.brand) if current.brand else brands.brand_for_prospect(current)
        scripts = _scripts_for(current, key)
        # Outreach always goes out under the commercial identity, so the
        # templates offered here are that side's, whatever the call is about.
        emails = _email_templates().get(brands.COMMERCIAL, [])
        try:
            import email_domains, product
            _, from_email, _ = brands.send_identity(brands.COMMERCIAL)
            can_email = (not product.domain()) or email_domains.may_send_as(from_email)
        except Exception:
            can_email = False

    return render_template(
        'admin/call_sheet.html',
        current=current,
        queue_left=len(queue),
        done_today=done,
        stint_over=stint_over,
        daily_stint=DAILY_STINT,
        scripts=scripts,
        emails=emails,
        can_email=can_email,
        quick_actions=prospecting.QUICK_ACTIONS,
        today=today,
        status_labels=Prospect.STATUS_LABELS,
        category_labels=Prospect.CATEGORY_LABELS,
        can_quote=_can_quote(),
        # Not offered to a number that has replied STOP.
        text_phone=(_phone10(current.phone)
                    if current and current.id not in _sms_stopped([current]) else ''),
    )


@places_finder_bp.route('/call/<int:prospect_id>/log', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def log_call(prospect_id):
    """Write the call down and go straight to the next one.

    Always stamps called_at, even for a phone that rang out: the count on the
    page is calls made, and a morning of nobody answering is still a morning's
    work. Without it the counter would say nought and the queue would look
    untouched.
    """
    p = Prospect.query.get_or_404(prospect_id)
    outcome = (request.form.get('outcome') or '').strip()
    if outcome in Prospect.STATUS_LABELS:
        p.status = outcome
    p.called_at = datetime.utcnow()
    _log_call(p, request.form, outcome)

    # The introduction, sent from the call rather than from a screen she has
    # to remember to go to afterwards. Sent after the outcome is written down,
    # so a refused send never costs her the call she just made.
    sent_note = ''
    if request.form.get('send_intro') == '1':
        ok, said = prospecting.send_outreach(
            p, request.form.get('email_subject'), request.form.get('email_body'),
            to=request.form.get('email'))
        sent_note = ' ' + said
        if not ok:
            flash(said, 'error')
    elif outcome == 'send_info':
        # The outcome that means "they asked me to email something" is the one
        # outcome where saying nothing is a lie by omission: she pressed a
        # button about sending information and the screen moved on to the next
        # business. Whether or not an email went, she finds out here.
        import email_domains
        import product
        try:
            import brands
            _, from_email, _ = brands.send_identity(brands.COMMERCIAL)
            allowed = (not product.domain()) or email_domains.may_send_as(from_email)
        except Exception:
            allowed = False
        if not allowed:
            sent_note = (' Nothing was emailed — introductions need your own '
                         'domain first (Settings → Sending Domain).')
        elif not (p.email or '').strip():
            sent_note = (' Nothing was emailed — no address for them yet.')
        else:
            sent_note = (' Nothing was emailed — open “Send them an '
                         'introduction” on the call to write one.')

    db.session.commit()

    if p.next_action and p.next_action_date:
        when = 'today' if p.next_action_date == local_today().isoformat() \
            else f'on {p.next_action_date}'
        flash(f'{p.business_name} — next: {p.next_action} {when}.{sent_note}',
              'success' if not sent_note.startswith(' Nothing') else 'info')
    else:
        flash(f'{p.business_name} — closed for now.{sent_note}', 'success')
    # Carry the "keep going" through to the next call, or the twenty-first
    # would hand her the finish line again.
    more = '1' if request.form.get('more') == '1' else None
    return redirect(url_for('places_finder.call_sheet', more=more))


@places_finder_bp.route('/import', methods=['POST'])
@login_required
def import_selected():
    import brands
    selected = request.form.getlist('selected')
    # Recorded from the search that found them rather than worked out later.
    # The category alone is not enough: "property management" turned out to be
    # residential managers buying turnover cleaning, not commercial janitorial.
    picked_brand = brands.normalize_lens(request.form.get('brand'))
    added = 0
    for pid in selected:
        raw = request.form.get(f'payload_{pid}')
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        # De-dupe by Google place id (falls back to name+city for demo rows).
        exists = None
        if data.get('place_id'):
            exists = Prospect.query.filter_by(place_id=data['place_id']).first()
        if not exists:
            exists = Prospect.query.filter_by(
                business_name=data.get('business_name'), city=data.get('city')
            ).first()
        if exists:
            continue
        db.session.add(Prospect(
            business_name=data.get('business_name', 'Unknown'),
            category=data.get('category', 'property_manager'),
            phone=data.get('phone', ''),
            website=data.get('website', ''),
            address=data.get('address', ''),
            city=data.get('city', ''),
            rating=data.get('rating'),
            place_id=data.get('place_id', ''),
            status='new',
            source='google_places',
            # ALL means the search wasn't run under one brand, so fall back to
            # working it out from the category rather than storing "all".
            brand=(picked_brand if picked_brand != brands.ALL
                   else brands.brand_for_prospect(data)),
        ))
        added += 1
    db.session.commit()
    flash(f'Added {added} business{"es" if added != 1 else ""} to your call list.', 'success')
    return redirect(url_for('places_finder.dashboard'))


def _back(view='today'):
    """Back to where the form was sent from -- the lead page, the call list --
    if that is a page on this site, else the call list. A form posting a
    `next` of somebody else's site must not turn this into a redirector."""
    back = (request.form.get('next') or request.args.get('next') or '').strip()
    if back.startswith('/') and not back.startswith('//') and '\\' not in back:
        return redirect(back)
    return redirect(url_for('places_finder.dashboard', view=view))


def _phone10(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else ''


@places_finder_bp.route('/add', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def add_by_hand():
    """A business you met, were referred to, or found yourself.

    Search was the only way onto the call list, so the best leads a cleaning
    company gets -- the office manager who asked at a networking breakfast, the
    property manager a customer passed on -- had nowhere to go except a note on
    somebody's phone. They go in here, and from then on they are worked exactly
    like anything search found: due today as a first call, logged, followed up,
    quoted.
    """
    import brands
    f = request.form
    name = (f.get('business_name') or '').strip()
    if not name:
        flash('Give the business a name.', 'error')
        return redirect(url_for('places_finder.dashboard', view='everyone'))
    city = (f.get('city') or '').strip()
    phone = (f.get('phone') or '').strip()

    # The same business twice means two people calling it, which is the one
    # thing a call list exists to prevent. Same number, or same name in the
    # same town, is the same business. A name alone is not: two referrals
    # to a franchise, neither with a town yet, are two businesses.
    mine = _phone10(phone)
    for p in Prospect.query.all():
        if ((mine and _phone10(p.phone) == mine)
                or (city and (p.business_name or '').strip().lower() == name.lower()
                    and (p.city or '').strip().lower() == city.lower())):
            flash(f'{p.business_name} is already on your list ({p.stage_label}).', 'info')
            return redirect(url_for('places_finder.dashboard', view='everyone'))

    category = f.get('category') if f.get('category') in CATEGORIES else 'office'
    website = (f.get('website') or '').strip()
    if website and not website.startswith(('http://', 'https://')):
        website = 'https://' + website
    # Residential or commercial, if they said; otherwise worked out from the
    # kind of business, the same way an imported lead is.
    kind = f.get('kind')
    if kind in ('residential', 'commercial'):
        picked = brands.COMMERCIAL if kind == 'commercial' else brands.PRIMARY
    else:
        picked = brands.normalize_lens(f.get('brand'))
    p = Prospect(
        business_name=name,
        category=category,
        contact_name=(f.get('contact_name') or '').strip() or None,
        phone=phone,
        email=(f.get('email') or '').strip() or None,
        website=website,
        address=(f.get('address') or '').strip(),
        city=city,
        status='new',
        stage='new',
        source='manual',
        brand=(picked if picked != brands.ALL
               else brands.brand_for_prospect({'category': category})),
        next_action='First call',
        next_action_date=local_today().isoformat(),
    )
    note = (f.get('notes') or '').strip()
    p.notes = prospecting.note_entry(p, 'Added by hand' + (f' — {note}' if note else ''))
    from flask import session
    if session.get('role') == 'team':
        p.agent = session.get('user_name')
    db.session.add(p)
    db.session.commit()
    flash(f'{name} is on your call list — first call due today.', 'success')
    # Straight to their page: the next thing anybody does with a lead they
    # just typed in is call, text or quote it, and that is all there.
    return redirect(url_for('places_finder.lead_page', prospect_id=p.id))


@places_finder_bp.route('/<int:prospect_id>')
@login_required
@requires_plan('lead_finder')
def lead_page(prospect_id):
    """One lead, start to finish, on one page.

    The call list is built for working through many businesses fast; this is
    for the one in front of you. Everything a lead goes through is here, in the
    order it happens: who they are (and correcting it -- a lead typed in as an
    office that turns out to be a restaurant), what was said on every call,
    texting and emailing them, the quote, and making them an account when they
    say yes. Before this, those were five screens and one of them -- making an
    account from a lead -- had no link to it at all.
    """
    from models import CommercialQuote, CommercialAccount, Lead, Message
    import brands
    p = Prospect.query.get_or_404(prospect_id)
    # Opened by link or bookmark, before any list view has filled in what
    # predates the funnel -- so do it here too, or an old won lead reads New.
    touched = [prospecting.backfill(p), brands.backfill(p, brands.brand_for_prospect)]
    if any(touched):
        db.session.commit()
    phone = _phone10(p.phone)
    quotes = (CommercialQuote.query.filter_by(prospect_id=p.id)
              .order_by(CommercialQuote.created_at.desc()).all())
    home_quotes = (Lead.query.filter_by(prospect_id=p.id)
                   .order_by(Lead.created_at.desc()).all())
    account = CommercialAccount.query.filter_by(prospect_id=p.id).first()
    texts = (Message.query.filter_by(phone=phone)
             .order_by(Message.created_at.desc()).limit(5).all()) if phone else []
    stages = [s for s in Prospect.STAGE_LABELS if s[0] in ('new', 'working', 'interested', 'proposal', 'won')]
    return render_template(
        'admin/lead_page.html', p=p, quotes=quotes, home_quotes=home_quotes,
        account=account, texts=list(reversed(texts)), stages=stages,
        stage_keys=[k for k, _ in stages],
        categories=CATEGORIES, category_labels=Prospect.CATEGORY_LABELS,
        status_labels=Prospect.STATUS_LABELS,
        next_rules={k: {'action': v[1], 'days': v[2]} for k, v in prospecting.RULES.items()},
        today=local_today().isoformat(),
        text_phone=phone if p.id not in _sms_stopped([p]) and p.status != 'do_not_contact' else '',
        # Contract quotes and accounts are owner pages (money), so their
        # prices and the account are only shown to whoever can open them.
        can_quote=_can_quote(), can_convert=_can_quote(),
        is_owner=_is_owner(),
        email_templates=_email_templates().get(brands.COMMERCIAL, []),
        here=url_for('places_finder.lead_page', prospect_id=p.id))


@places_finder_bp.route('/<int:prospect_id>/edit', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def edit_lead(prospect_id):
    """Correct who a lead is. The kind of business especially: it decides
    which scripts are read, how the quote is priced and which company the
    emails come from, and the first guess -- typed in a hurry, or Google's
    -- is often wrong."""
    import brands
    p = Prospect.query.get_or_404(prospect_id)
    f = request.form
    name = (f.get('business_name') or '').strip()
    if name:
        p.business_name = name
    old_category = p.category
    if f.get('category') in CATEGORIES:
        p.category = f.get('category')
    for field in ('contact_name', 'phone', 'email', 'address', 'city', 'renewal_note'):
        if field in f:
            setattr(p, field, (f.get(field) or '').strip() or None)
    if 'website' in f:
        site = (f.get('website') or '').strip()
        if site and not site.startswith(('http://', 'https://')):
            site = 'https://' + site
        p.website = site or None
    # The radio always submits whichever side is showing, so it only counts as
    # a choice when it differs from what the page was drawn with. Otherwise
    # correcting a property manager to an office would keep it residential.
    kind = f.get('kind')
    if kind in ('residential', 'commercial') and kind != f.get('kind_was'):
        p.brand = brands.COMMERCIAL if kind == 'commercial' else brands.PRIMARY
    elif p.category != old_category:
        # A new kind of business with no explicit choice: follow it, the same
        # way a lead added by hand does.
        p.brand = brands.brand_for_prospect(p)
    db.session.commit()
    flash(f'{p.business_name} updated.', 'success')
    return redirect(url_for('places_finder.lead_page', prospect_id=p.id))


@places_finder_bp.route('/<int:prospect_id>/kind', methods=['POST'])
@login_required
def set_kind(prospect_id):
    """Residential or commercial, said by a person rather than guessed.

    The category decides it until somebody knows better, and the guess is
    often wrong in both directions: a property manager who also runs an office
    block wants a janitorial contract, and a general contractor wants a house
    cleaned after a build. Which way it goes decides the quote it gets, the
    scripts read to it, and whose name the emails go out under.
    """
    import brands
    p = Prospect.query.get_or_404(prospect_id)
    kind = request.form.get('kind')
    if kind in ('residential', 'commercial'):
        p.brand = brands.COMMERCIAL if kind == 'commercial' else brands.PRIMARY
        db.session.commit()
        flash(f'{p.business_name} is now {p.kind_label.split(" ", 1)[1].lower()} — '
              f'its quote, scripts and emails follow.', 'success')
    back = request.form.get('next') or ''
    if not back.startswith('/') or back.startswith('//') or '\\' in back:
        back = url_for('places_finder.dashboard', view='everyone')
    return redirect(back)


@places_finder_bp.route('/<int:prospect_id>/status', methods=['POST'])
@login_required
def update_status(prospect_id):
    p = Prospect.query.get_or_404(prospect_id)
    new_status = request.form.get('status')
    logged = request.form.get('mode') == 'log'

    if new_status in Prospect.STATUS_LABELS:
        p.status = new_status
        if new_status != 'new' and not p.called_at:
            p.called_at = datetime.utcnow()

    if logged:
        _log_call(p, request.form, new_status)
    elif 'notes' in request.form:
        # The quick inline edit in the table still replaces outright.
        p.notes = request.form.get('notes', '')

    db.session.commit()
    if logged:
        if p.next_action and p.next_action_date:
            when = 'today' if p.next_action_date == local_today().isoformat() \
                else f'on {p.next_action_date}'
            flash(f'Logged. Next: {p.next_action} — {when}.', 'success')
        else:
            flash(f'Logged. {p.business_name} is closed for now.', 'success')
    else:
        flash('Call list updated.', 'success')
    return _back(request.args.get('view', 'today'))


@places_finder_bp.route('/<int:prospect_id>/snooze', methods=['POST'])
@login_required
def snooze(prospect_id):
    """Push a due prospect out without pretending a call happened.

    Without this the only way to clear something off Today is to log a call you
    didn't make, which puts a lie in the notes and inflates the attempt count.
    """
    p = Prospect.query.get_or_404(prospect_id)
    try:
        days = max(1, min(365, int(request.form.get('days', 3))))
    except (TypeError, ValueError):
        days = 3
    p.next_action = p.next_action or 'Follow-up call'
    p.next_action_date = (local_today() + timedelta(days=days)).isoformat()
    db.session.commit()
    flash(f'{p.business_name} moved to {p.next_action_date}.', 'success')
    return _back(request.args.get('view', 'today'))


@places_finder_bp.route('/<int:prospect_id>/email', methods=['POST'])
@login_required
def send_outreach(prospect_id):
    """Send one of the outreach emails to a prospect and log it as a touch."""
    p = Prospect.query.get_or_404(prospect_id)
    view = request.args.get('view', 'today')
    # The sending itself lives in prospecting.send_outreach, because the
    # assistant offers this too and two copies of it is how one of them stops
    # logging the touch without anybody noticing.
    ok, said = prospecting.send_outreach(
        p, request.form.get('subject'), request.form.get('body'),
        to=request.form.get('email'))
    flash(said, 'success' if ok else 'error')
    return _back(view)


@places_finder_bp.route('/export.csv')
@login_required
def export_csv():
    """The whole call list as a spreadsheet — every contact detail and where
    each one is in the funnel. Hers to keep, and the thing to hand a VA."""
    rows = _backfilled()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Business', 'Category', 'Stage', 'Last outcome', 'Attempts',
                'Contact', 'Phone', 'Email', 'Website', 'Address', 'City',
                'Rating', 'Next action', 'Next action date', 'Contract renewal',
                'Last called', 'Last emailed', 'Added', 'Notes'])
    for p in sorted(rows, key=lambda x: (x.business_name or '').lower()):
        w.writerow([
            p.business_name, p.category_label, p.stage_label, p.status_label,
            p.attempts or 0, p.contact_name or '', p.phone or '', p.email or '',
            p.website or '', p.address or '', p.city or '',
            f'{p.rating:.1f}' if p.rating else '',
            p.next_action or '', p.next_action_date or '', p.renewal_note or '',
            p.called_at.strftime('%Y-%m-%d') if p.called_at else '',
            p.last_emailed_at.strftime('%Y-%m-%d') if p.last_emailed_at else '',
            p.created_at.strftime('%Y-%m-%d') if p.created_at else '',
            (p.notes or '').replace('\r', ' '),
        ])
    stamp = local_today().isoformat()
    return Response(buf.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition': f'attachment; filename=call-list-{stamp}.csv'})


def _log_call(prospect, form, outcome):
    """Write down a call and schedule whatever comes next.

    Lifted out of update_status so the call sheet records a call exactly the
    way the drawer always has -- one way of writing a call down, not two that
    drift apart.
    """
    # Details worth having as fields rather than buried in prose: you can't
    # email a note, and "call them before the renewal" needs a date.
    for field, attr in (('contact', 'contact_name'), ('email', 'email'),
                        ('renewal', 'renewal_note')):
        val = (form.get(field) or '').strip()
        if val:
            setattr(prospect, attr, val)

    # Each save prepends a dated entry instead of overwriting, so the renewal
    # date and what they actually said survive the next call.
    prospect.notes = _prepend_log(prospect, form)

    # A booked walkthrough is what the call was for, so the date they agreed
    # becomes the next action outright, rather than the table's "book the
    # walkthrough in two days" -- which is advice for a call that has not
    # happened yet. It then shows on the calendar beside the cleans, which is
    # where somebody looks the night before.
    walkthrough = (form.get('walkthrough_date') or '').strip()
    action = (form.get('next_action') or '').strip() or None
    when = (form.get('next_action_date') or '').strip() or None
    if outcome == 'interested' and walkthrough:
        action, when = 'Walkthrough', walkthrough

    # Where they are now, and what happens next. A blank action here means the
    # caller took the suggestion; an explicit one overrules it.
    return prospecting.apply_outcome(
        prospect, outcome, next_action=action, next_action_date=when)


def _prepend_log(prospect, form):
    """Build one dated call-log entry and put it above the existing notes."""
    from scheduling import local_now

    facts = []
    if form.get('contact', '').strip():
        facts.append('Contact: ' + form['contact'].strip())
    if form.get('renewal', '').strip():
        facts.append('Renewal: ' + form['renewal'].strip())
    if form.get('sqft', '').strip():
        facts.append('Size: ' + form['sqft'].strip())

    header = local_now().strftime('[%b %d] ') + Prospect.STATUS_LABELS.get(
        prospect.status, prospect.status or 'New')
    if facts:
        header += ' · ' + ' · '.join(facts)

    entry = header
    body = form.get('log_note', '').strip()
    if body:
        entry += '\n' + body

    return (entry + '\n\n' + (prospect.notes or '')).strip()


@places_finder_bp.route('/<int:prospect_id>/delete', methods=['POST'])
@login_required
def delete(prospect_id):
    p = Prospect.query.get_or_404(prospect_id)
    db.session.delete(p)
    db.session.commit()
    flash('Removed from call list.', 'success')
    return redirect(url_for('places_finder.dashboard'))
