"""What a brand-new business still has to do before it can take real bookings.

A CRM handed over with nothing filled in is daunting, and the parts that are
missing aren't obvious — a business can look fine and still be quietly unable to
email a customer. This turns "is it ready?" into a list the owner can work down
on her own, which is the whole point: nobody should have to ask the person who
sold them the software whether their setup is finished.

Ordered by what would hurt most if it were skipped.
"""


# What `setup_complete` has to say to count as finished.
#
# The flag is written once and read on every page after, so an established
# business is not recomputing its onboarding forever. That is the right trade
# until the list itself changes -- and when it gained the timezone, the terms,
# payments and how balances are collected, every company already carrying a
# plain '1' would have gone on being told it had finished a list it had never
# been shown. A version here means they are asked once more, and then latched
# again. Bump it whenever a required step is added.
SETUP_VERSION = '2'


def checklist():
    from models import BusinessSetting, Booking
    import integrations
    from owner_cleaner import hired_team_count

    def setting(key):
        return bool((BusinessSetting.get(key) or '').strip())

    status = integrations.status()
    stripe_live = status['stripe']['mode'] == 'live'

    items = [
        {
            'key': 'business',
            'title': 'Add your business name and contact details',
            'why': 'These appear on every invoice, quote and email your customers receive.',
            'done': setting('business_name') and setting('phone') and setting('email'),
            'link': '/settings/business',
            'critical': True,
        },
        {
            'key': 'payments',
            'title': 'Connect Stripe so you can take payments',
            'why': ('Without it, customers cannot pay by card and the payment links do nothing.'
                    if not status['stripe']['ready'] else
                    'Connected in test mode — real cards will not be charged until you paste your live key.'),
            'done': stripe_live,
            'partial': status['stripe']['ready'] and not stripe_live,
            'link': '/settings/connections',
            'critical': True,
        },
        {
            'key': 'email',
            'title': 'Connect your email service',
            'why': 'Booking confirmations, invoices and receipts all go out by email.',
            'done': status['email']['ready'],
            'link': '/settings/connections',
            'critical': True,
        },
        {
            'key': 'texting',
            'title': 'Connect texting',
            'why': 'Cleaners get their job offers by text. Without it they get email instead, which is slower.',
            'done': status['texting']['ready'],
            'link': '/settings/connections',
            'critical': False,
        },
        {
            'key': 'pricing',
            'title': 'Set your prices',
            'why': 'The CRM quotes jobs from these. Until they are yours, it is quoting somebody else\'s numbers.',
            'done': setting('pricing_reviewed'),
            'link': '/settings/pricing',
            'critical': True,
        },
        {
            'key': 'terms',
            'title': 'Read and adjust your customer terms',
            'why': ('Your customers agree to these when they book, and you are the one who has to stand '
                    'behind them. They ship as a starting draft, not legal advice.'),
            'done': setting('terms_reviewed'),
            'link': '/settings/business',
            'critical': True,
        },
        {
            'key': 'team',
            'title': 'Add a team member when you hire',
            'why': ('You are already on the team, so you can assign jobs to yourself. '
                    'Add people here when you are ready to send work to someone else.'),
            'done': hired_team_count() > 0,
            'link': '/contractors/team',
            'critical': False,
        },
        {
            'key': 'booking',
            'title': 'Create a test booking and walk it through',
            'why': 'Book it, send the confirmation, take a payment, assign a cleaner. Best to find problems on a fake job.',
            'done': Booking.query.count() > 0,
            'link': '/bookings/new',
            'critical': False,
        },
    ]
    if integrations.hosted_company():
        # Akye provides email and texting; there is nothing for the owner to
        # connect, so they are not steps on her list.
        items = [i for i in items if i['key'] not in ('email', 'texting')]
    return items


def summary():
    items = checklist()
    done = sum(1 for i in items if i['done'])
    blocking = [i for i in items if i['critical'] and not i['done']]
    return {
        'items': items,
        'done': done,
        'total': len(items),
        'blocking': blocking,
        'complete': not blocking,
    }


# ── The path to a first real job ────────────────────────────────────────────
#
# The checklist above is about configuration: is this business able to email a
# customer, take a card, quote a price. It is the right list and it is the wrong
# first screen. Somebody who has just signed up does not know what any of it is
# for yet, and eight equally-weighted items with no order is a shape people
# close the tab on.
#
# This is the other question: has the software done its job once? A business is
# only really using a CRM when a real job is on the calendar with a real cleaner
# assigned to it. Everything before that is setup; everything after is work.
#
# So this is a single line, in order, with one thing to do next. Not a list of
# twelve equal calls to action -- one.

def journey():
    """Everything between signing up and being able to trade, in order.

    Two kinds of step, and the difference matters more than the order does.

    Required steps are configuration: they can all be done on the first
    evening, by somebody who has no cleaners and no customers yet, and until
    they are done the business cannot actually take money. Four of them used
    to be missing from here entirely -- the timezone everything is scheduled
    against, the terms customers agree to, the Stripe connection without
    which every payment link is decoration, and whether balances are
    collected at all. Two of those four fail silently: a business that never
    picks a timezone is quietly scheduled in New York, and one that never
    chooses a collection mode never charges a balance. Nothing errors. The
    money simply does not arrive.

    Optional steps are the business's own world -- a cleaner, a customer, a
    job. They used to be required, which asked somebody on their first
    evening to invent a customer they did not have in order to finish setup.
    They are offered, never insisted on, and they no longer gate anything.
    """
    import automations
    import integrations
    from models import BusinessSetting, Booking, BookingCrew

    def setting(key):
        return bool((BusinessSetting.get(key) or '').strip())

    # The owner is the first cleaner (owner_cleaner.py), so having staff says
    # nothing; what says something is having hired somebody else.
    from owner_cleaner import hired_team_count
    has_team = hired_team_count() > 0
    has_client = False
    try:
        from models import Client
        has_client = Client.query.count() > 0
    except Exception:
        pass
    bookings = Booking.query.count()
    # Assigned means a named cleaner, by either route -- a crew row, or the
    # single-cleaner field older jobs use.
    assigned = (BookingCrew.query.count() > 0
                or Booking.query.filter(Booking.assigned_cleaner.isnot(None)).count() > 0)

    # The demo has no real keys and cannot be given any -- demo_guard blanks
    # every outbound credential on purpose -- so "connect payments" is a step
    # it could never finish. Not applicable is not the same as not done, the
    # same way the hosted product drops email and texting from the checklist.
    demo = False
    try:
        import demo_guard
        demo = demo_guard.active()
    except Exception:
        pass

    steps = [
        # ── Required: four, and only one of them is typing ────────────────
        #
        # Everything here ships with a working default, so a business that
        # never finishes is already quoting real customers -- with somebody
        # else's prices, under a generic contract, in New York time. These
        # are not blanks to fill in. They are the defaults that are wrong for
        # this particular business, and the whole of setup is confirming
        # them.
        # The phone, and only the phone. The timezone is derived -- from the
        # ZIP at signup, or from the ZIP whenever one arrives -- so requiring
        # it here made the step impossible for every company that signed up
        # before the ZIP field existed: nothing in the chat asked for a
        # timezone, so nothing could ever finish the step, and the banner
        # kept pointing back at it. A step nobody can complete is worse than
        # a step that is missing.
        {'key': 'business', 'required': True,
         'done': setting('phone'),
         'title': 'Check your details',
         'why': 'What customers see on every quote, invoice and reminder.',
         'cta': 'Check them', 'link': '/settings/business'},
        {'key': 'pricing', 'required': True, 'done': setting('pricing_reviewed'),
         'title': 'Confirm your prices',
         'why': 'Until you look, Akye is quoting somebody else’s numbers.',
         'cta': 'Confirm prices', 'link': '/settings/pricing'},
        {'key': 'terms', 'required': True, 'done': setting('terms_reviewed'),
         'title': 'Accept your customer terms',
         'why': 'Customers agree to these when they book. A standard draft is '
                'already in force until you say otherwise.',
         'cta': 'Read and accept', 'link': '/settings/business'},
        {'key': 'balance', 'required': True,
         'done': bool((BusinessSetting.get('balance_collection') or '').strip()),
         'title': 'Decide how balances get paid',
         'why': 'When a job is done, the rest can come off the card on file, or '
                'wait for you. Until you choose, nothing is taken.',
         'cta': 'Choose', 'link': '/settings/automations'},
        # ── Tracked, never blocking ───────────────────────────────────────
        #
        # Payments is not on the required list, because a business can take
        # bookings without it and demanding a Stripe account in the first two
        # minutes is how somebody decides this is too much. It is not
        # optional either: until it is done no card is ever charged. So it
        # sits here, amber from the first screen and red once it has been
        # put off long enough, and it blocks nothing in between.
        {'key': 'payments', 'required': False, 'urgent': True,
         'done': integrations.stripe_mode() == 'live',
         'title': 'Connect payments',
         'why': 'You can take bookings now. You cannot take card payments until '
                'this is done — your bank details stay with you.',
         'cta': 'Connect payments', 'link': '/settings/connections'},
        # ── Optional: your own world in it ────────────────────────────────
        #
        # Offered one at a time, never as a list of four. These are first
        # use, not setup, and a business waiting on its first customer has
        # finished setting up.
        {'key': 'booking_page', 'video': 'booking_page', 'required': False,
         'done': setting('booking_page_shared'),
         'title': 'Share your booking page',
         'why': 'You already have one — customers pick what they want, see your '
                'price and book themselves. It just needs to be somewhere they '
                'will see it.',
         'cta': 'Show me my page', 'link': '/settings/booking-page'},
        {'key': 'client', 'video': 'team_and_customer', 'required': False,
         'done': has_client,
         'title': 'Add a customer',
         'why': 'One you already clean for.',
         'cta': 'Add a customer', 'link': '/bookings/clients/new',
         'secondary': {'label': 'Already have a customer list? Import it instead',
                       'link': '/migration'}},
        # You are already the first cleaner (owner_cleaner.py), so a job can be
        # assigned to you the moment it exists. Nobody has to be hired first.
        {'key': 'job', 'video': 'book_job', 'required': False,
         'done': bookings > 0 and assigned,
         'title': 'Schedule a job and assign it',
         'why': 'Give it to yourself to start. When you add a cleaner, they get '
                'a text with the address, the price and the checklist.',
         'cta': 'Book a job', 'link': '/bookings/new'},
        {'key': 'team', 'video': 'team_and_customer', 'required': False,
         'done': has_team,
         'title': 'Add a team member when you hire',
         'why': 'You are on the team already. Add people when you are ready to '
                'send work to someone else.',
         'cta': 'Add a team member', 'link': '/staff/new',
         'secondary': {'label': 'Already have a team? Import them all at once',
                       'link': '/migration'}},
    ]
    if demo:
        steps = [s for s in steps if s['key'] != 'payments']
    return steps


PAYMENTS_RED_AFTER_DAYS = 3


def payments_state():
    """How loudly to ask about payments: '', 'amber' or 'red'.

    Amber the moment setup is finished, red once it has been put off for
    three days. Never blocking either way -- the business can work, it just
    cannot be paid by card, and that is a fact to keep in front of somebody
    rather than a door to hold shut.
    """
    from datetime import datetime, timedelta
    import integrations
    from models import BusinessSetting
    if integrations.stripe_mode() == 'live':
        return ''
    ready = (BusinessSetting.get('ready_at') or '').strip()
    if not ready:
        return 'amber'
    try:
        since = datetime.fromisoformat(ready)
    except ValueError:
        return 'amber'
    return 'red' if datetime.utcnow() - since > timedelta(
        days=PAYMENTS_RED_AFTER_DAYS) else 'amber'


def _mark_ready():
    """Stamp the moment the required steps were finished. Once, quietly."""
    from datetime import datetime
    from extensions import db
    from models import BusinessSetting
    if (BusinessSetting.get('ready_at') or '').strip():
        return
    try:
        BusinessSetting.set('ready_at', datetime.utcnow().isoformat(timespec='seconds'))
        db.session.commit()
    except Exception:
        db.session.rollback()


def progress():
    """Where a business is on that path, and the single next thing to do.

    Two different questions used to share one answer, and they are not the same
    question:

    `activated` — has this business put its real world into the software? A
    cleaner they employ and a customer they clean for. That is the moment it
    stops being a demo: somebody who has entered a person and a customer has
    enough in front of them to judge the product, and somebody who has not,
    has not. It is a milestone, and what the setup emails and the Funnel
    watch for. It does not start or move the trial, which runs 30 days from
    signup.

    `complete` — has every setup step been done? A longer list, and the right
    condition for putting the getting-started card away.

    Neither drives billing any more: the trial is thirty days from signup
    whatever a business does. `activated` is kept because when somebody first
    put their own world into the software is worth knowing, and `complete`
    because it is what puts the getting-started card away.
    """
    steps = journey()
    required = [s for s in steps if s.get('required')]
    if all(s['done'] for s in required):
        _mark_ready()
    optional = [s for s in steps if not s.get('required')]
    done = sum(1 for s in required if s['done'])
    # Required first, then the rest: the order of `steps` already says this,
    # so the next thing to do is simply the next unfinished one.
    nxt = next((s for s in steps if not s['done']), None)
    by_key = {s['key']: bool(s['done']) for s in steps}
    return {
        'steps': steps,
        # Counted over the required steps only. A solo owner with no
        # customers yet is not 60% set up, she is finished -- and a progress
        # bar that can never reach the end is a bar nobody finishes.
        'done': done,
        'total': len(required),
        'percent': int(round(done / len(required) * 100)) if required else 100,
        'optional_done': sum(1 for s in optional if s['done']),
        'optional_total': len(optional),
        'next': nxt,
        'next_required': next((s for s in required if not s['done']), None),
        # The activation milestone: a customer, and a job on the calendar with
        # somebody assigned -- the owner counts, as the first cleaner. A company
        # that hired a team and added a customer before scheduling anything is
        # activated too, as it always was.
        'activated': by_key.get('client', False) and (
            by_key.get('job', False) or by_key.get('team', False)),
        # How hard to push about payments, which is tracked rather than
        # required. '' once it is connected.
        'payments': payments_state(),
        # Able to trade. The optional steps are offered after this and never
        # hold the card open: a business waiting on its first customer has
        # finished setting up, whatever it has not typed in yet.
        'complete': all(s['done'] for s in required),
    }
