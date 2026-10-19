"""What a brand-new business still has to do before it can take real bookings.

A CRM handed over with nothing filled in is daunting, and the parts that are
missing aren't obvious — a business can look fine and still be quietly unable to
email a customer. This turns "is it ready?" into a list the owner can work down
on her own, which is the whole point: nobody should have to ask the person who
sold them the software whether their setup is finished.

Ordered by what would hurt most if it were skipped.
"""


def checklist():
    from models import BusinessSetting, Staff, Booking
    import integrations

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
            'title': 'Add your cleaners',
            'why': 'You need at least one person to send a job to.',
            'done': Staff.query.count() > 0,
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
    from models import BusinessSetting, Staff, Booking, BookingCrew

    def setting(key):
        return bool((BusinessSetting.get(key) or '').strip())

    has_staff = Staff.query.filter_by(is_active=True).count() > 0
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
        # ── Required: able to trade ──────────────────────────────────────
        {'key': 'business', 'required': True,
         'done': setting('business_name') and setting('phone') and setting('email'),
         'title': 'Tell us about your business',
         'why': 'Your name goes on every quote, invoice and text your customers get.',
         'cta': 'Add your details', 'link': '/settings/business'},
        # Early, because everything after it is scheduled against it. The
        # default is New York and nothing complains, so a business in Texas
        # sends tomorrow's reminders an hour wrong forever and has no reason
        # to suspect it.
        {'key': 'timezone', 'required': True, 'done': setting('timezone'),
         'title': 'Set your timezone',
         'why': 'Reminders, the day’s plan and your end-of-day numbers are all worked out '
                'where you are. Left alone it assumes New York.',
         'cta': 'Set my timezone', 'link': '/settings/business'},
        {'key': 'pricing', 'required': True, 'done': setting('pricing_reviewed'),
         'title': 'Check your prices',
         'why': 'The CRM quotes from these. Until you have looked, it is quoting somebody else’s numbers.',
         'cta': 'Review prices', 'link': '/settings/pricing'},
        {'key': 'terms', 'required': True, 'done': setting('terms_reviewed'),
         'title': 'Read your customer terms',
         'why': 'Your customers agree to these when they book, and you are the one who has '
                'to stand behind them. They ship as a starting draft, not legal advice.',
         'cta': 'Read the terms', 'link': '/settings/business'},
        {'key': 'payments', 'required': True,
         'done': integrations.stripe_mode() == 'live',
         'title': 'Connect payments',
         'why': 'Until this is done every payment link is decoration — deposits, balances '
                'and receipts all go through it. Your bank details stay with you.',
         'cta': 'Connect payments', 'link': '/settings/connections'},
        # Written down or not, this is a decision. Unanswered it means `ask`,
        # which means balances are never taken and the money sits owed.
        {'key': 'balance', 'required': True,
         'done': bool((BusinessSetting.get('balance_collection') or '').strip()),
         'title': 'Decide how balances get paid',
         'why': 'When a job is done, the rest can come off the card on file automatically, '
                'or wait for you to say so. Until you choose, nothing is taken.',
         'cta': 'Choose', 'link': '/settings/automations'},
        # ── Optional: your own world in it ───────────────────────────────
        # `booking_page_shared`, not `booking_page_seen`. The old flag was set
        # by opening /book — which is where this step's own button went, so the
        # step ticked itself the moment anybody clicked it and then sat there
        # crossed out above a business that had shared nothing.
        {'key': 'booking_page', 'video': 'booking_page', 'required': False, 'done': setting('booking_page_shared'),
         'title': 'Share your booking page',
         'why': 'You already have one — a page where customers pick what they want, '
                'see your price and book themselves. It just needs to be somewhere '
                'they will see it, like your Facebook bio.',
         'cta': 'Show me my page', 'link': '/settings/booking-page'},
        {'key': 'team', 'video': 'team_and_customer', 'required': False, 'done': has_staff,
         'title': 'Add a cleaner',
         'why': 'You need somebody to send a job to. Add yourself if you are still cleaning.',
         'cta': 'Add a cleaner', 'link': '/staff/new',
         # A business coming off a spreadsheet or another system does not
         # have "a cleaner" to add, it has a roster -- typing them in one at
         # a time here is exactly the retyping the Migration Toolbox exists
         # to skip.
         'secondary': {'label': 'Already have a team? Import them all at once',
                       'link': '/migration'}},
        {'key': 'client', 'video': 'team_and_customer', 'required': False, 'done': has_client,
         'title': 'Add a customer',
         'why': 'One you already clean for. Real is better than made up — you will see how it works.',
         'cta': 'Add a customer', 'link': '/bookings/clients/new',
         'secondary': {'label': 'Already have a customer list? Import it instead',
                       'link': '/migration'}},
        {'key': 'job', 'video': 'book_job', 'required': False, 'done': bookings > 0 and assigned,
         'title': 'Schedule a job and assign it',
         'why': 'This is the moment it starts being useful — the cleaner gets a text with the address, '
                'the price and the checklist.',
         'cta': 'Book a job', 'link': '/bookings/new'},
    ]
    if demo:
        steps = [s for s in steps if s['key'] != 'payments']
    return steps


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
        # The trial trigger. Both, not either: a cleaner with nobody to clean
        # for, or a customer with nobody to send, is half a setup and shows
        # nothing working end to end.
        'activated': by_key.get('team', False) and by_key.get('client', False),
        # Able to trade. The optional steps are offered after this and never
        # hold the card open: a business waiting on its first customer has
        # finished setting up, whatever it has not typed in yet.
        'complete': all(s['done'] for s in required),
    }
