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
