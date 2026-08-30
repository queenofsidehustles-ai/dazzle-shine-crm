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
    """The five steps between signing up and the software being useful."""
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

    return [
        {'key': 'business', 'done': setting('business_name'),
         'title': 'Tell us about your business',
         'why': 'Your name goes on every quote, invoice and text your customers get.',
         'cta': 'Add your details', 'link': '/settings/business'},
        {'key': 'pricing', 'done': setting('pricing_reviewed'),
         'title': 'Check your prices',
         'why': 'The CRM quotes from these. Until you have looked, it is quoting somebody else’s numbers.',
         'cta': 'Review prices', 'link': '/settings/pricing'},
        {'key': 'booking_page', 'done': setting('booking_page_seen'),
         'title': 'Share your booking page',
         'why': 'Your own page, in your colours, quoting your prices. Put the link '
                'in your Facebook bio and customers can book without ringing you.',
         'cta': 'See your page', 'link': '/book'},
        {'key': 'team', 'done': has_staff,
         'title': 'Add a cleaner',
         'why': 'You need somebody to send a job to. Add yourself if you are still cleaning.',
         'cta': 'Add a cleaner', 'link': '/staff/new'},
        {'key': 'client', 'done': has_client,
         'title': 'Add a customer',
         'why': 'One you already clean for. Real is better than made up — you will see how it works.',
         'cta': 'Add a customer', 'link': '/bookings/clients'},
        {'key': 'job', 'done': bookings > 0 and assigned,
         'title': 'Schedule a job and assign it',
         'why': 'This is the moment it starts being useful — the cleaner gets a text with the address, '
                'the price and the checklist.',
         'cta': 'Book a job', 'link': '/bookings/new'},
    ]


def progress():
    """Where a business is on that path, and the single next thing to do.

    `activated` is the number worth watching above all others. Not signups, not
    logins -- a job on the calendar with a cleaner assigned to it. That is when
    the product has been useful once, and it is the moment somebody stops
    evaluating and starts depending on it.
    """
    steps = journey()
    done = sum(1 for s in steps if s['done'])
    nxt = next((s for s in steps if not s['done']), None)
    return {
        'steps': steps,
        'done': done,
        'total': len(steps),
        'percent': int(round(done / len(steps) * 100)) if steps else 0,
        'next': nxt,
        'activated': nxt is None,
    }
