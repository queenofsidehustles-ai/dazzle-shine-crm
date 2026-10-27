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
                   flash, Response, abort)
import entitlements
from entitlements import requires_plan
from auth import login_required
from extensions import db
from models import Prospect
import commercial_pricing
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
    # Only the side of the business currently on screen, and only the leads
    # this person works. Done here rather than in each view so Today, the call
    # sheet, Everyone and the export can't disagree about it.
    return _mine(brands.filter_rows(rows, brands.brand_for_prospect))


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
        # A rep's counts are of the leads they work, not the whole company's.
        counts=_status_counts() if _rep() is None else {
            'all': len(prospects),
            **{k: sum(1 for p in prospects if p.status == k) for k in ('new', 'called', 'interested', 'won')}},
        due=prospecting.due_counts(_workable(prospects)),
        my_rep=_rep(),
        reps=_reps() if _is_owner() else [],
        rep_filter='',
        my_progress=_my_progress(),
        ready_count=sum(1 for p in prospects if p.ready_to_quote_at),
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
        is_owner=_is_owner(),
        can_text=_role_may('messages.read'),
        can_home_quote=_role_may('lead.manage'),
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


def _role_may(permission):
    """Whether the signed-in role holds a permission (the owner holds all)."""
    from flask import session
    import rbac
    return _is_owner() or rbac.has_permission(session.get('role'), permission)


def _is_owner():
    from auth import is_owner_session
    try:
        return is_owner_session()
    except Exception:
        return False


def _rep():
    """The signed-in Sales rep's name, or None for anybody who works every lead.

    A rep works their own leads and the unassigned pool, never a teammate's:
    two people ringing the same business is the thing a call list exists to
    prevent, and a rep's commission is what they bring in, not what somebody
    else did. The owner -- and the older roles -- see everything.
    """
    from flask import session
    return session.get('user_name') if session.get('role') == 'sales' else None


def _mine(rows):
    """The rows the signed-in person works: all of them, or a rep's own plus
    the unassigned pool."""
    rep = _rep()
    if rep is None:
        return rows
    return [p for p in rows if not p.agent or p.agent == rep]


def _lead(prospect_id):
    """A lead by id, as long as the signed-in person may work it. A rep asking
    for a teammate's gets the same 404 as a lead that does not exist."""
    p = Prospect.query.get_or_404(prospect_id)
    rep = _rep()
    if rep is not None and p.agent and p.agent != rep:
        abort(404)
    return p


def _take(p):
    """Make an unassigned lead the signed-in rep's, if nobody beat them to it.

    One conditional UPDATE, not a read and then a write: two reps opening the
    pool at the same moment both read it as unassigned, and only the database
    can say which of them got there first. The row stays locked until the
    request commits, so the second rep's UPDATE waits and then matches
    nothing. True when the lead is (now) theirs, or when nobody is a rep.
    """
    from sqlalchemy import or_
    rep = _rep()
    if rep is None or p.agent == rep:
        return True
    if p.agent:
        return False
    taken = (Prospect.query
             .filter(Prospect.id == p.id, or_(Prospect.agent.is_(None), Prospect.agent == ''))
             .update({Prospect.agent: rep}, synchronize_session=False))
    if taken:
        p.agent = rep
        return True
    db.session.refresh(p)
    return p.agent == rep


def _claim(p):
    """A rep who works an unassigned lead takes it: it is theirs from the first
    call, for the follow-ups and for the commission. If a teammate took it a
    moment ago, it is theirs, and this rep gets what _lead gives for a
    teammate's lead."""
    if not _take(p):
        abort(404)


def _my_progress():
    """A rep's calls today against their target, for the top of their list;
    None for anybody without a target."""
    rep = _rep()
    if rep is None:
        return None
    import rep_activity
    me = _me()
    if me is None:
        return None
    done, target = rep_activity.calls_today(me.id), rep_activity.target_for(me)
    return {'done': done, 'target': target, 'pct': min(100, round(100 * done / target))}


def _me():
    """The signed-in login's User row, or None (the env owner has none)."""
    from flask import session
    from models import User
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None


def _workable(rows):
    """The leads still the signed-in person's to chase. A rep's part ends at
    the hand-off: a lead waiting on the owner's quote is not a call to make,
    so it leaves their Today and their call sheet (it stays in Everyone)."""
    if _rep() is None:
        return rows
    return [p for p in rows if not p.ready_to_quote_at]


def _reps():
    """Who a lead can be assigned to: the active Sales logins. Not the legacy
    "team" role -- it cannot open the call list, so a lead given to one would
    sit where nobody can work it."""
    from models import User
    return (User.query.filter(User.role == 'sales', User.active.is_(True))
            .order_by(User.name).all())


def _record(p, kind, outcome=None):
    """Write down that the signed-in person did something on a lead -- what
    the owner's Team page and a rep's own numbers are counted from. Added to
    the session; it is saved with whatever the route commits."""
    from flask import has_request_context, session
    from models import ProspectActivity
    # Outside a request (a script, a test) nobody is signed in to credit.
    who = session if has_request_context() else {}
    db.session.add(ProspectActivity(
        prospect_id=p.id, business_name=(p.business_name or '')[:200],
        user_id=who.get('user_id'),
        user_name=who.get('user_name') or ('Owner' if who.get('logged_in') else None),
        kind=kind, outcome=(outcome or None) and str(outcome)[:30]))


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
    if view not in ('today', 'everyone', 'find', 'month', 'add', 'ready'):
        view = 'today'
    stage_filter = (request.args.get('stage') or '').strip()
    rows = _backfilled()
    # Counted before the rep filter: the tab is the owner's whole queue of
    # leads to price, whichever rep's list is on screen.
    ready_count = sum(1 for p in rows if p.ready_to_quote_at)
    # The owner can look at one rep's leads, or the ones nobody has yet.
    rep_filter = (request.args.get('rep') or '').strip() if _is_owner() else ''
    if rep_filter == 'unassigned':
        rows = [p for p in rows if not p.agent]
    elif rep_filter:
        rows = [p for p in rows if p.agent == rep_filter]

    if view == 'today':
        # Prospect.is_due is the one definition of due, shared with the
        # dashboard count. It was written out longhand here, and a prospect
        # resting in nurture could never satisfy it however overdue it got.
        today = local_today().isoformat()
        shown = sorted([p for p in _workable(rows) if p.is_due(today)],
                       key=prospecting.due_sort_key)
    elif view == 'ready':
        # Handed over by a rep, waiting on a price: oldest first.
        shown = sorted([p for p in rows if p.ready_to_quote_at], key=lambda p: p.ready_to_quote_at)
    elif view == 'everyone':
        pool = [p for p in rows if (p.stage or 'new') == stage_filter] \
            if stage_filter else rows
        shown = sorted(pool, key=lambda p: (p.business_name or '').lower())
    elif view == 'month':
        # The commercial month. Callbacks are not appointments -- they have no
        # time and take four minutes -- so they do not belong on the jobs
        # calendar. They do belong somewhere you can see a fortnight ahead and
        # notice that the week of the 14th has eleven of them in it.
        shown = sorted(_workable(rows), key=prospecting.due_sort_key)
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
        for p in _workable(rows):
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
                                        stage_filter=stage_filter,
                                        **dict(extra, rep_filter=rep_filter,
                                               ready_count=ready_count)))


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
    queue = sorted([p for p in _workable(rows) if p.is_due(today)],
                   key=prospecting.due_sort_key)
    rep = _rep()
    if rep is None:
        done = sum(1 for p in rows
                   if p.called_at and p.called_at.date().isoformat() == today)
        stint = DAILY_STINT
    else:
        # A rep's own calls against their own target: the leads' last-called
        # stamps are anybody's calls, and a lead rung twice counts once.
        import rep_activity
        me = _me()
        done = rep_activity.calls_today(me.id) if me else 0
        stint = rep_activity.target_for(me)

    # A sitting worth of calls, then a finish line. An endless queue is how a
    # backlog becomes a screen nobody opens: there is no version of today where
    # you get to the bottom, so there is no reason to start. Twenty is a
    # morning. Anybody who wants to keep going says so.
    stint_over = (done >= stint
                  and not prospect_id
                  and request.args.get('more') != '1')

    if prospect_id:
        current = _lead(prospect_id)
        _claim(current)
    else:
        # The sheet puts one business in front of a rep, so that is when it
        # becomes theirs -- not at their first click, by which time a
        # teammate may be ringing it too. One already taken is skipped.
        current = None if stint_over else next((p for p in queue if _take(p)), None)
    if _rep() is not None:
        db.session.commit()
        # Less any a teammate took while this one was being reserved.
        queue = _mine(queue)

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

    # The softphone (voice.py). All of it is computed here so the page only
    # ever shows what the server would also accept.
    import integrations
    import voice
    from models import CallLog
    calling = {'ready': integrations.voice_ready(), 'block': None,
               'used': voice.calls_this_month(), 'limit': voice.MONTHLY_CALLS,
               'recording': voice.recording_on(), 'keep_days': voice.RECORDING_KEEP_DAYS, 'past': []}
    if current is not None:
        calling['block'] = voice.refusal(current) if calling['ready'] else None
        calling['past'] = (CallLog.query.filter_by(prospect_id=current.id)
                           .order_by(CallLog.created_at.desc()).limit(5).all())

    return render_template(
        'admin/call_sheet.html',
        current=current,
        calling=calling,
        is_owner=_is_owner(),
        queue_left=len(queue),
        done_today=done,
        stint_over=stint_over,
        daily_stint=stint,
        my_rep=rep,
        scripts=scripts,
        emails=emails,
        can_email=can_email,
        quick_actions=prospecting.QUICK_ACTIONS,
        today=today,
        status_labels=Prospect.STATUS_LABELS,
        category_labels=Prospect.CATEGORY_LABELS,
        can_quote=_can_quote(),
        can_home_quote=_role_may('lead.manage'),
        # Not offered to a number that has replied STOP, nor to a role that
        # cannot open the inbox.
        text_phone=(_phone10(current.phone)
                    if current and current.id not in _sms_stopped([current])
                    and _role_may('messages.read') else ''),
        # Without the inbox (a Sales rep), texting is done on the lead's page.
        lead_text=bool(current and _phone10(current.phone)
                       and current.id not in _sms_stopped([current])
                       and current.status != 'do_not_contact'
                       and not _role_may('messages.read')),
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
    p = _lead(prospect_id)
    _claim(p)
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
        if ok:
            _record(p, 'email')
        else:
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
    # Found by a Sales (or legacy team) login: theirs, for commission -- the
    # same as a lead they type in by hand.
    from flask import session
    finder_agent = (session.get('user_name')
                    if session.get('role') in ('team', 'sales') else None)
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
            agent=finder_agent,
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
            rep = _rep()
            if rep is not None and p.agent and p.agent != rep:
                flash(f'{p.business_name} is already on the call list — a teammate is working it.', 'info')
            else:
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
    if session.get('role') in ('team', 'sales'):
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
    p = _lead(prospect_id)
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
    if texts and not _role_may('messages.read'):
        # A thread is keyed by phone number, and a number on a lead can also
        # be a customer's, a cleaner's or an applicant's. Without the inbox,
        # the conversation is shown only when the number is this lead's and
        # nobody else's -- the same test the inbox uses to label it.
        from blueprints.messages import resolve_contact
        if resolve_contact(phone).get('prospect_id') != p.id:
            texts = []
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
        can_text_lead=_role_may('prospect.work'),
        my_rep=_rep(),
        reps=_reps() if _is_owner() else [],
        # Contract quotes and accounts are owner pages (money), so their
        # prices and the account are only shown to whoever can open them.
        can_quote=_can_quote(), can_convert=_can_quote(),
        is_owner=_is_owner(),
        # Texting opens the inbox, and the home quote is a website-leads
        # page: neither is part of a Sales login's job, so neither is offered.
        can_text=_role_may('messages.read'),
        can_home_quote=_role_may('lead.manage'),
        email_templates=_email_templates().get(brands.COMMERCIAL, []),
        walk=prospecting.walkthrough(p),
        walk_summary=prospecting.walkthrough_summary(prospecting.walkthrough(p)),
        walk_price=prospecting.walkthrough_price(p),
        walk_services=prospecting.WALKTHROUGH_SERVICES,
        walk_items=commercial_pricing.WORK_ITEMS,
        walk_area_presets=commercial_pricing.AREA_PRESETS,
        walk_frequencies=prospecting.WALKTHROUGH_FREQUENCIES,
        walk_booked=(p.next_action or '').lower().startswith('walkthrough'),
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
    p = _lead(prospect_id)
    _claim(p)
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
    _save_renewal_month(p, f)
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


@places_finder_bp.route('/<int:prospect_id>/walkthrough/book', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def book_walkthrough(prospect_id):
    """Put the walkthrough in the diary: it becomes the lead's next step, so
    it is on the call list and the calendar the day it is due."""
    p = _lead(prospect_id)
    _claim(p)
    when = (request.form.get('date') or '').strip()
    at = (request.form.get('time') or '').strip()[:20]
    try:
        from datetime import date as _date
        _date.fromisoformat(when)
    except ValueError:
        flash('Pick the day of the walkthrough.', 'error')
        return redirect(url_for('places_finder.lead_page', prospect_id=p.id))
    p.next_action = f'Walkthrough at {at}' if at else 'Walkthrough'
    p.next_action_date = when
    if (p.stage or 'new') in ('new', 'working'):
        p.stage = 'interested'
    p.notes = prospecting.note_entry(p, f'Walkthrough booked for {when}' + (f' at {at}' if at else ''))
    _record(p, 'walkthrough_booked')
    db.session.commit()
    from flask import session
    _tell_owner(p, f'Walkthrough booked: {p.business_name}, {when}' + (f' at {at}' if at else ''), [
        f'{session.get("user_name") or "Your team"} booked a walkthrough at {p.business_name} '
        f'for {when}' + (f' at {at}' if at else '') + '.',
        f'Address: {p.address or p.city or "—"}',
        f'Contact: {p.contact_name or "—"} · {p.phone or "no phone"}',
    ])
    flash(f'Walkthrough booked for {when}. It is on the calendar.', 'success')
    return redirect(url_for('places_finder.lead_page', prospect_id=p.id))


@places_finder_bp.route('/<int:prospect_id>/walkthrough', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def save_walkthrough(prospect_id):
    """What the walkthrough found. It is what the quote is written from, so
    the next step becomes writing it -- today, while it is fresh."""
    import json
    from datetime import datetime
    p = _lead(prospect_id)
    _claim(p)
    w = prospecting.walkthrough_from_form(request.form)
    if not p.walkthrough_at:
        # Counted once: saving it again is correcting it, not a second visit.
        _record(p, 'walkthrough')
    p.walkthrough = json.dumps(w)
    p.walkthrough_at = datetime.utcnow()
    summary = prospecting.walkthrough_summary(w)
    p.notes = prospecting.note_entry(
        p, 'Walkthrough done' + (f' — {summary}' if summary else '')
        + (f'\n{w["notes"]}' if w.get('notes') else ''))
    handed = False
    if (p.stage or 'new') in ('new', 'working', 'interested'):
        p.stage = 'interested'
        p.next_action = 'Write and send the quote'
        p.next_action_date = local_today().isoformat()
        # A rep's walkthrough is the hand-off: the owner writes the quote.
        # Once: saving it again is a correction, not a second hand-off (or a
        # second email to the owner).
        if not _is_owner() and not p.ready_to_quote_at:
            _hand_over(p)
            handed = True
    db.session.commit()
    if handed:
        _tell_owner(p, f'Ready to quote: {p.business_name} (walkthrough by {p.ready_by})', [
            f'{p.ready_by} did the walkthrough at {p.business_name}. It is ready for you to quote.',
            f'Found: {summary}' if summary else '',
            f'Noticed: {w["notes"]}' if w.get('notes') else '',
        ])
        flash('Walkthrough saved and handed to the owner to quote.', 'success')
    else:
        flash('Walkthrough saved. Next: the quote — it is filled in from this.', 'success')
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
    p = _lead(prospect_id)
    _claim(p)
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
    p = _lead(prospect_id)
    _claim(p)
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
    p = _lead(prospect_id)
    _claim(p)
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
    p = _lead(prospect_id)
    _claim(p)
    view = request.args.get('view', 'today')
    # The sending itself lives in prospecting.send_outreach, because the
    # assistant offers this too and two copies of it is how one of them stops
    # logging the touch without anybody noticing.
    ok, said = prospecting.send_outreach(
        p, request.form.get('subject'), request.form.get('body'),
        to=request.form.get('email'))
    if ok:
        _record(p, 'email')
        db.session.commit()
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


def _save_renewal_month(prospect, form):
    """Record the renewal as a date, which is the half that can act.

    `renewal_note` has always taken "March 2027" and
    prospecting.wake_renewals() has always read `renewal_date` -- and nothing
    wrote it, so the wake-up could not fire however many renewal months were
    collected. A month is the honest precision: nobody knows the day their
    cleaning contract ends, and asking for one gets a guess typed into a
    required field.

    Shared by every screen that records one, because there are three now --
    the drawer, the call sheet and the lead page -- and capturing it on some
    of them is how this went unnoticed in the first place.
    """
    month = (form.get('renewal_date') or '').strip()
    if not month:
        return
    # <input type="month"> gives YYYY-MM. Anchor it to the first, so the
    # thirty-day lead time lands inside the month before.
    prospect.renewal_date = f'{month}-01' if len(month) == 7 else month[:10]
    # A renewal that moved is a new decision, not the old one repeated.
    prospect.renewal_woken_at = None


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

    _save_renewal_month(prospect, form)

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
    _record(prospect, 'call', outcome)
    if outcome == 'interested' and walkthrough:
        action, when = 'Walkthrough', walkthrough
        _record(prospect, 'walkthrough_booked')

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


@places_finder_bp.route('/<int:prospect_id>/text', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def text_lead(prospect_id):
    """Text this lead, and only this lead.

    A rep follows up by text as much as by phone, but texting meant the inbox
    -- every customer's and every cleaner's conversation. This sends to the
    lead's own number from the lead page, through the inbox's own delivery
    (so it is translated, logged and shows in the owner's inbox like any
    other), and never to a number that replied STOP or asked not to hear
    from us."""
    from blueprints.messages import deliver
    from notifications import sms_opted_out
    p = _lead(prospect_id)
    _claim(p)
    phone10 = _phone10(p.phone)
    body = (request.form.get('body') or '').strip()[:1000]
    here = url_for('places_finder.lead_page', prospect_id=p.id) + '#texts'
    if not phone10:
        flash('There is no mobile number on this lead to text.', 'error')
        return redirect(here)
    if not body:
        flash('Type a message first.', 'error')
        return redirect(here)
    if p.status == 'do_not_contact' or sms_opted_out(phone10):
        flash('Not sent — they asked not to be contacted, or replied STOP.', 'error')
        db.session.commit()
        return redirect(here)
    ok, detail = deliver(phone10, body, {'name': p.contact_name or p.business_name})
    # The history says what reached them. A failed send is still written
    # down -- so nobody re-sends blind or wonders why there was no reply --
    # but as a failure, not as a touch.
    p.notes = prospecting.note_entry(
        p, f'Texted: {body}' if ok else f'Text failed ({detail}): {body}')
    if ok:
        _record(p, 'text')
    db.session.commit()
    flash('Text sent.' if ok else 'The text did not go: ' + detail,
          'success' if ok else 'error')
    return redirect(here)


def _tell_owner(p, subject, lines):
    """Email the owner about something a rep did on a lead -- a walkthrough
    to turn up to, a lead to price. Not when it is the owner doing it, and
    never fatal: the lead is saved whether or not the email goes."""
    if _is_owner():
        return
    try:
        import branding
        import notifications
        from markupsafe import escape as e
        to = branding.owner_email()
        if not to:
            return
        link = url_for('places_finder.lead_page', prospect_id=p.id, _external=True)
        html = ('<div style="font-family:Inter,Arial,sans-serif;max-width:560px;color:#1f1333">'
                + ''.join(f'<p style="margin:0 0 10px">{e(x)}</p>' for x in lines if x)
                + f'<p><a href="{link}" style="color:#b98a33;font-weight:700">Open {e(p.business_name)} &rarr;</a></p></div>')
        notifications.send_email(to_email=to, to_name=branding.biz_name(), subject=subject, html=html)
    except Exception:
        pass


def _hand_over(p, note=''):
    """Mark a lead ready for the owner to quote. The rep's part is done: the
    lead is qualified and the walkthrough found what the quote needs."""
    from datetime import datetime
    from flask import session
    p.ready_to_quote_at = datetime.utcnow()
    p.ready_by = session.get('user_name') or 'the team'
    if (p.stage or 'new') in ('new', 'working'):
        p.stage = 'interested'
    p.next_action = 'Write and send the quote'
    p.next_action_date = local_today().isoformat()
    p.notes = prospecting.note_entry(
        p, f'Handed over for a quote by {p.ready_by}' + (f': {note}' if note else ''))
    _record(p, 'handoff')


@places_finder_bp.route('/<int:prospect_id>/ready', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def ready_to_quote(prospect_id):
    """A rep hands a qualified lead to the owner to price."""
    p = _lead(prospect_id)
    here = url_for('places_finder.lead_page', prospect_id=p.id)
    # Only an open lead nobody has handed over yet. A second tab, a double
    # tap or an old page would otherwise drag a quoted or won lead back to
    # Interested and email the owner about it again.
    if p.ready_to_quote_at:
        flash(f'{p.business_name} is already with the owner to quote.', 'info')
        return redirect(here)
    if (p.stage or 'new') not in ('new', 'working', 'interested'):
        stage = dict(Prospect.STAGE_LABELS).get(p.stage, p.stage)
        flash(f'{p.business_name} is past the hand-off already ({stage}).', 'error')
        return redirect(here)
    _claim(p)
    note = (request.form.get('note') or '').strip()[:500]
    _hand_over(p, note)
    db.session.commit()
    summary = prospecting.walkthrough_summary(prospecting.walkthrough(p))
    _tell_owner(p, f'Ready to quote: {p.business_name} (from {p.ready_by})', [
        f'{p.ready_by} has qualified {p.business_name} and handed it to you to quote.',
        f'Walkthrough: {summary}' if summary else 'No walkthrough recorded yet.',
        f'Their note: {note}' if note else '',
        f'Contact: {p.contact_name or "—"} · {p.phone or "no phone"} · {p.email or "no email"}',
    ])
    flash(f'{p.business_name} is with the owner to quote.', 'success')
    return redirect(url_for('places_finder.lead_page', prospect_id=p.id))


_NOT_A_REP = object()


def _assignee(value):
    """A rep's name from the assign form; None when the owner picked
    "Unassigned"; _NOT_A_REP for anything else -- a rep disabled since the
    page was drawn, or a hand-edited form -- which must change nothing rather
    than quietly empty the lead into the pool."""
    value = (value or '').strip()
    if not value:
        return None
    return value if value in {u.name for u in _reps()} else _NOT_A_REP


@places_finder_bp.route('/<int:prospect_id>/assign', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def assign(prospect_id):
    """Give a lead to a rep, move it to another, or put it back in the pool.
    The owner's: rbac lists it with the other owner-only endpoints."""
    p = _lead(prospect_id)
    agent = _assignee(request.form.get('agent'))
    if agent is _NOT_A_REP:
        flash('That person is not an active Sales login — nothing was changed.', 'error')
        return redirect(url_for('places_finder.lead_page', prospect_id=p.id))
    p.agent = agent
    db.session.commit()
    flash(f'{p.business_name} is now {p.agent}\u2019s.' if p.agent
          else f'{p.business_name} is back in the unassigned pool.', 'success')
    if not (request.form.get('next') or '').strip():
        return redirect(url_for('places_finder.lead_page', prospect_id=p.id))
    return _back('everyone')


@places_finder_bp.route('/assign', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def assign_many():
    """Hand a batch of leads to a rep from the Everyone list -- a morning's
    calling for a new hire, or a leaver's leads to somebody else."""
    ids = [int(i) for i in request.form.getlist('ids') if str(i).isdigit()][:500]
    agent = _assignee(request.form.get('agent'))
    if agent is _NOT_A_REP:
        flash('That person is not an active Sales login — nothing was changed.', 'error')
        return redirect(url_for('places_finder.dashboard', view='everyone',
                                rep=request.form.get('rep_filter') or None))
    rows = Prospect.query.filter(Prospect.id.in_(ids)).all() if ids else []
    for p in rows:
        p.agent = agent
    db.session.commit()
    who = agent or 'the unassigned pool'
    flash(f'{len(rows)} lead{"" if len(rows) == 1 else "s"} moved to {who}.' if rows
          else 'Tick the leads to move first.', 'success' if rows else 'error')
    return redirect(url_for('places_finder.dashboard', view='everyone',
                            rep=request.form.get('rep_filter') or None))


def _numbers(users, period):
    """Each rep's activity for a period, by login, and the accounts it won
    them (accounts are credited by name, like their commission)."""
    import rep_activity
    first, last = rep_activity.period_dates(period)
    got = rep_activity.counts([u.id for u in users], first, last)
    won = rep_activity.won([u.name for u in users], first, last)
    for u in users:
        got[u.id]['won'] = len(won.get(u.name, []))
    return got, first, last


@places_finder_bp.route('/team')
@login_required
@requires_plan('lead_finder')
def team():
    """The owner's view of the reps: calls against target today, what a
    period of calling turned into, and the latest of what they did.

    Owner-only (rbac): a rep's numbers are between them and the owner, and a
    rep sees their own on My numbers."""
    import rep_activity
    import va_commission
    period = request.args.get('period', 'week')
    if period not in dict(rep_activity.PERIODS):
        period = 'week'
    reps = _reps()
    names = [u.name for u in reps]
    today = local_today()
    ids = [u.id for u in reps]
    calls_today = rep_activity.counts(ids, today, today)
    got, first, last = _numbers(reps, period)
    open_leads = dict(
        db.session.query(Prospect.agent, db.func.count(Prospect.id))
        .filter(Prospect.agent.in_(names or ['']),
                db.func.coalesce(Prospect.stage, 'new').in_(Prospect.LIVE_STAGES))
        .group_by(Prospect.agent).all())
    pay = entitlements.can('va_commissions')
    rows = []
    for u in reps:
        target = rep_activity.target_for(u)
        rows.append({
            'user': u, 'target': target, 'own_target': u.daily_call_target,
            'today': calls_today[u.id]['call'],
            'pct': min(100, round(100 * calls_today[u.id]['call'] / target)),
            'n': got[u.id], 'open': open_leads.get(u.name, 0),
            'earned': (va_commission.commission_for_month(u.name, today.year, today.month)['total']
                       if pay else None),
        })
    who = (request.args.get('rep') or '').strip()
    feed = rep_activity.recent([u.id for u in reps if u.name == who] if who in names else ids, limit=40)
    return render_template(
        'admin/lead_team.html', rows=rows, period=period, periods=rep_activity.PERIODS,
        first=first, last=last, default_target=rep_activity.default_target(),
        feed=feed, feed_rep=who if who in names else '', kinds=_activity_kinds(),
        status_labels=Prospect.STATUS_LABELS, pay=pay,
        month=f'{today.year:04d}-{today.month:02d}')


def _activity_kinds():
    from models import ProspectActivity
    return ProspectActivity.KINDS


def _target(value):
    """A calls-a-day number from a form: 1 to 500, or None when left blank."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        n = int(value)
    except ValueError:
        raise ValueError(value)
    if not 1 <= n <= 500:
        raise ValueError(value)
    return n


@places_finder_bp.route('/team/targets', methods=['POST'])
@login_required
@requires_plan('lead_finder')
def set_targets():
    """The company's calls a day, and any rep's own number. A rep left blank
    follows the company's."""
    from models import BusinessSetting
    import rep_activity
    back = redirect(url_for('places_finder.team', period=request.form.get('period') or None))
    try:
        # The company's number cannot be "nothing": every rep without their
        # own would have no target. Only a rep's own box may be left blank.
        default = _target(request.form.get('default')) if 'default' in request.form else None
        if 'default' in request.form and default is None:
            raise ValueError('')
        own = {u: _target(request.form.get(f'target_{u.id}'))
               for u in _reps() if f'target_{u.id}' in request.form}
    except ValueError as e:
        what = f'"{e}" is not a number of calls' if str(e) else 'The company\'s calls a day cannot be blank'
        flash(f'{what} — use a whole number from 1 to 500. Nothing was changed.', 'error')
        return back
    if default:
        BusinessSetting.set('sales_daily_calls', default)
    for u, n in own.items():
        u.daily_call_target = n
    db.session.commit()
    flash(f'Targets saved. Anyone without their own makes '
          f'{default or rep_activity.default_target()} calls a day.', 'success')
    return back


@places_finder_bp.route('/me')
@login_required
@requires_plan('lead_finder')
def my_numbers():
    """A rep's own page: calls against today's target, what this week and
    month have come to, and what they have earned -- worked out the same way
    as the owner's commission report, from the same rates, so the two never
    disagree about what somebody is owed."""
    import rep_activity
    import va_commission
    from models import CommercialAccount, CommissionPayment
    rep = _rep()
    if rep is None:
        return redirect(url_for('places_finder.team') if _is_owner()
                        else url_for('places_finder.dashboard'))
    today = local_today()
    me = _me()
    if me is None:
        return redirect(url_for('places_finder.dashboard'))
    target = rep_activity.target_for(me)
    done = rep_activity.calls_today(me.id)
    week, *_ = _numbers([me], 'week')
    month, *_ = _numbers([me], 'month')
    mine = Prospect.query.filter(Prospect.agent == rep).all()
    leads = {
        'open': sum(1 for p in mine if (p.stage or 'new') in Prospect.LIVE_STAGES),
        'waiting': sum(1 for p in mine if p.ready_to_quote_at),
        'accounts': CommercialAccount.query.filter(CommercialAccount.agent == rep).count(),
    }
    pay = entitlements.can('va_commissions')
    earnings = None
    if pay:
        last_y, last_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        this = va_commission.commission_for_month(rep, today.year, today.month)
        prev = va_commission.commission_for_month(rep, last_y, last_m)
        earnings = {
            'this': this, 'prev': prev,
            'prev_paid': CommissionPayment.query.filter_by(agent=rep, year=last_y, month=last_m).first(),
            'this_label': today.strftime('%B'),
            'prev_label': today.replace(day=1).replace(year=last_y, month=last_m).strftime('%B'),
            'rates': va_commission.get_rates(),
        }
    walk_pay = None
    if pay:
        import walkthrough_pay
        this_wk, last_wk = walkthrough_pay.week_of(today), walkthrough_pay.last_week_start(today)
        walk_pay = {'rate': walkthrough_pay.rate(),
                    'this': walkthrough_pay.week_for_user(me.id, this_wk),
                    'last': walkthrough_pay.week_for_user(me.id, last_wk),
                    'last_start': last_wk}
    return render_template(
        'admin/lead_my_numbers.html', target=target, done=done, walk_pay=walk_pay,
        pct=min(100, round(100 * done / target)), week=week[me.id], month=month[me.id],
        leads=leads, earnings=earnings, feed=rep_activity.recent([me.id], limit=15),
        kinds=_activity_kinds(), status_labels=Prospect.STATUS_LABELS)


@places_finder_bp.route('/<int:prospect_id>/delete', methods=['POST'])
@login_required
def delete(prospect_id):
    p = _lead(prospect_id)
    # Calls already placed stay (they count toward the month); they just stop
    # pointing at a business that is gone.
    from models import CallLog
    CallLog.query.filter_by(prospect_id=p.id).update({'prospect_id': None})
    db.session.delete(p)
    db.session.commit()
    flash('Removed from call list.', 'success')
    return redirect(url_for('places_finder.dashboard'))
