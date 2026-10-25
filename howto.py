"""Step-by-step guides for the things owners do most, with "Show me".

## Why this exists

Asked "how do I book a job?", Nana used to find a paragraph that said where
booking happens and paraphrase it -- two options and no steps. Owners asked
for the steps themselves, and for the screen to point at the button (Monica,
2026-10-25). So each guide here is a short numbered list in the words on the
buttons, and each step can name the element on the real page to highlight.

## How a guide is shaped

    {'key':      'book-job',                    # also the ?tour= value
     'title':    'Book a job',
     'keywords': [...],                         # how owners ask for it
     'steps': [
        {'say':    'Press ➕ New Booking.',      # what Nana and the bubble say
         'page':   r'^/bookings/?$',           # where it happens (path regex)
         'start':  '/bookings/',                # where "Take me there" goes
         'target': 'new-booking'},              # data-tour="..." on that page
        ...]}

`target` is the value of a `data-tour` attribute in the template. A step with
no target is shown as a bubble in the middle of the page. A step whose page is
a particular booking (`^/bookings/\\d+$`) has a `start` that is the list it is
opened from, so "Take me there" never needs an id it does not have.

Every sentence has to be true of the app as it is: Nana repeats these to
paying customers. When a screen changes, change its guide in the same commit;
tests/test_howto_guides.py checks every target is still on its page.
"""
import re

# Pages the guides walk through, as path patterns. A record page (one
# booking, one cleaner) has a \d in it, and its steps start from the list.
_BOOKINGS = r'^/bookings/?$'
_BOOKING = r'^/bookings/\d+$'
_TEAM = r'^/contractors/team/?$'
_CLEANER = r'^/contractors/team/\d+$'
_LEADS = r'^/find-leads/?$'
_LEAD = r'^/find-leads/\d+$'
_CALL = r'^/find-leads/call(/\d+)?$'
_ACCOUNTS = r'^/commercial/?$'
_ACCOUNT = r'^/commercial/\d+$'
_APPS = r'^/contractors/applications/?$'
_APP = r'^/contractors/applications/\d+$'


def _open_booking(say='Open Bookings and press the customer\'s name (or View) to open the booking.'):
    return {'say': say, 'page': _BOOKINGS, 'start': '/bookings/', 'target': 'bookings-list'}


def _open_cleaner(say='Open Team and press the cleaner\'s card.'):
    return {'say': say, 'page': _TEAM, 'start': '/contractors/team', 'target': 'team-cards'}


def _open_lead(say='Open Commercial, press 🏢 Everyone and press the business\'s name.'):
    return {'say': say, 'page': _LEADS, 'start': '/find-leads/?view=everyone', 'target': 'leads-everyone'}


def _open_application(say='Open Hiring and press Review next to the applicant.'):
    return {'say': say, 'page': _APPS, 'start': '/contractors/applications', 'target': 'applications-list'}


GUIDES = [
    {
        'key': 'book-job',
        'title': 'Book a job',
        'keywords': ['book a job', 'new booking', 'book a clean', 'schedule a clean', 'schedule a job',
                     'add a booking', 'make a booking', 'create a job', 'add a job', 'phone booking', 'book'],
        'steps': [
            {'say': 'Open Bookings and press ➕ New Booking.',
             'page': _BOOKINGS, 'start': '/bookings/', 'target': 'new-booking'},
            {'say': 'Under 1. Who, type the customer\'s name, phone, email and address.',
             'page': r'^/bookings/new$', 'start': '/bookings/new', 'target': 'booking-who'},
            {'say': 'Under 2. What, pick the type of cleaning, bedrooms, bathrooms and any add-ons. '
                    'Leave Price empty and your price list is used.',
             'page': r'^/bookings/new$', 'start': '/bookings/new', 'target': 'booking-what'},
            {'say': 'Under 3. When, choose the date and time.',
             'page': r'^/bookings/new$', 'start': '/bookings/new', 'target': 'booking-when'},
            {'say': 'Press ✅ Book it. With "Text + email the customer their confirmation" ticked, '
                    'they are sent the details.',
             'page': r'^/bookings/new$', 'start': '/bookings/new', 'target': 'booking-save'},
            {'say': 'The booking opens. Give it to a cleaner in Who\'s doing it.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'assign-card'},
        ],
    },
    {
        'key': 'assign-cleaner',
        'title': 'Assign a cleaner to a job',
        'keywords': ['assign', 'assign a cleaner', 'assign cleaner', 'give a job', 'give the job',
                     'send a job', 'dispatch', 'who is cleaning', 'put a cleaner on', 'offer to team',
                     'work order', 'unassigned'],
        'steps': [
            _open_booking(),
            {'say': 'In Who\'s doing it, pick the cleaner under Assign to. Or pick '
                    '"Offer it to the whole team" and the first to claim it gets it.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'assign-to'},
            {'say': 'Leave She gets paid empty for the usual pay, or type the amount for this job.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'assign-pay'},
            {'say': 'Keep "Send the work order now" ticked and press Assign & send. She is sent '
                    'the address, her pay and the checklist.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'assign-send'},
        ],
    },
    {
        'key': 'confirm-deposit',
        'title': 'Confirm a booking and ask for the deposit',
        'keywords': ['confirm a booking', 'confirm booking', 'confirmation', 'send confirmation',
                     'deposit', 'ask for the deposit', 'ask for a deposit', 'deposit link',
                     'request deposit', 'take a deposit'],
        'steps': [
            _open_booking(),
            {'say': 'At the top of the booking, in Confirm with the customer, check the box next '
                    'to Send says "Confirmation + ask for the $… deposit". It is chosen for you '
                    'when you take deposits.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'confirm-send'},
            {'say': 'Press Send. One email and text carries the confirmation and the link to pay '
                    'the deposit. When they pay, the booking is confirmed and their card is saved '
                    'for the balance. Your deposit amount is set on Pricing, under Deposit.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'confirm-send'},
        ],
    },
    {
        'key': 'send-quote',
        'title': 'Send a quote',
        'keywords': ['send a quote', 'quote', 'quotes', 'estimate', 'give a price', 'price quote',
                     'quote a caller', 'quoting'],
        'steps': [
            {'say': 'Open Leads and press ✉️ Quote a caller.',
             'page': r'^/leads/?$', 'start': '/leads/', 'target': 'quote-caller'},
            {'say': 'Type their name and email. Add their phone to text it too.',
             'page': r'^/leads/quote/new$', 'start': '/leads/quote/new', 'target': 'quote-who'},
            {'say': 'Pick the service, bedrooms and bathrooms, and tick any add-ons.',
             'page': r'^/leads/quote/new$', 'start': '/leads/quote/new', 'target': 'quote-job'},
            {'say': 'Check "Cleaning price you quoted them". Leave it empty to use the calculated price.',
             'page': r'^/leads/quote/new$', 'start': '/leads/quote/new', 'target': 'quote-price'},
            {'say': 'Press Send this quote. It is emailed, and texted too while "Text it to them as well" '
                    'is ticked. Their link books at exactly this price.',
             'page': r'^/leads/quote/new$', 'start': '/leads/quote/new', 'target': 'quote-send'},
        ],
    },
    {
        'key': 'share-booking-page',
        'title': 'Share your booking page',
        'keywords': ['booking page', 'booking link', 'share my booking page', 'share the link',
                     'online booking', 'book online', 'link in bio', 'website', 'embed'],
        'steps': [
            {'say': 'This is your booking page\'s link. Press Copy link. Preview shows it the way a customer sees it.',
             'page': r'^/settings/booking-page$', 'start': '/settings/booking-page', 'target': 'booking-link'},
            {'say': 'Paste it in your Facebook or Instagram bio, your Google Business Profile, your email '
                    'signature, and texts to people who ask for a price.',
             'page': r'^/settings/booking-page$', 'start': '/settings/booking-page', 'target': 'booking-where'},
            {'say': 'Tick "I\'ve put my booking link somewhere customers will see it". That ticks the '
                    'step off Getting started.',
             'page': r'^/settings/booking-page$', 'start': '/settings/booking-page', 'target': 'booking-shared'},
        ],
    },
    {
        'key': 'connect-payments',
        'title': 'Connect Stripe to take card payments',
        'keywords': ['connect stripe', 'stripe', 'connect payments', 'take card payments', 'card payments',
                     'get paid by card', 'api keys', 'stripe keys', 'payments setup'],
        'steps': [
            {'say': 'In Stripe — taking payments, open "How do I get my Stripe keys?". In Stripe you '
                    'copy them from Developers, then API keys.',
             'page': r'^/settings/connections$', 'start': '/settings/connections', 'target': 'stripe-keys'},
            {'say': 'Paste the Publishable key and the Secret key into the boxes and press Save Stripe Keys. '
                    'Test keys (pk_test_, sk_test_) let you try it without charging a real card.',
             'page': r'^/settings/connections$', 'start': '/settings/connections', 'target': 'stripe-save'},
            {'say': 'Press 💳 Test Stripe connection and check it names your business.',
             'page': r'^/settings/connections$', 'start': '/settings/connections', 'target': 'stripe-test'},
        ],
    },
    {
        'key': 'charge-balance',
        'title': 'Charge the balance after the clean',
        'keywords': ['charge the balance', 'charge balance', 'balance', 'collect payment', 'take payment',
                     'charge the card', 'charge card', 'get paid', 'mark paid', 'still due', 'payment after'],
        'steps': [
            _open_booking(),
            {'say': 'In The money, Still due is what is left to collect.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'money-card'},
            {'say': 'If their card is saved, press Charge $… Now. If not, press 💳 Take a card payment '
                    'to take their card.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'take-card-payment'},
            {'say': 'Paid in cash, Zelle or Venmo? Pick it, set the date the money came in and press ✓ Mark paid.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'mark-paid'},
            {'say': 'To charge saved cards by themselves, choose "Charge the card on the day" under Charge balances.',
             'page': r'^/settings/automations$', 'start': '/settings/automations', 'target': 'balance-mode'},
        ],
    },
    {
        'key': 'pay-cleaners',
        'title': 'Pay your cleaners',
        'keywords': ['pay cleaners', 'pay my cleaners', 'pay a cleaner', 'payroll', 'payout', 'pay the team',
                     'pay staff', 'what do i owe', 'record pay', 'already paid'],
        'steps': [
            {'say': 'Open Money, then Payroll. Set Week Start and Week End and press Calculate.',
             'page': r'^/contractors/payroll$', 'start': '/contractors/payroll', 'target': 'payroll-week'},
            {'say': 'Each cleaner has her completed jobs listed with what she is owed. Only jobs marked '
                    'Completed with a cleaner on them are shown.',
             'page': r'^/contractors/payroll$', 'start': '/contractors/payroll'},
            {'say': 'Paid her yourself? Pick Cash, Zelle, Venmo, Check or Bank / ACH and press ✓ Already paid. '
                    'If she is set up on Stripe, 💸 Pay sends it through Stripe.',
             'page': r'^/contractors/payroll$', 'start': '/contractors/payroll'},
        ],
    },
    {
        'key': 'add-cleaner',
        'title': 'Add a cleaner',
        'keywords': ['add a cleaner', 'add cleaner', 'new cleaner', 'add team member', 'add staff',
                     'add an employee', 'add someone', 'hire someone i know'],
        'steps': [
            {'say': 'Open Team and press + Add someone directly.',
             'page': _TEAM, 'start': '/contractors/team', 'target': 'add-cleaner'},
            {'say': 'Type their full name, phone and email. Give each person a different name.',
             'page': r'^/staff/new$', 'start': '/staff/new', 'target': 'staff-name'},
            {'say': 'Under How they\'re paid, pick % of the job or Per hour and type the rate. Leave the '
                    'rate empty to set it later.',
             'page': r'^/staff/new$', 'start': '/staff/new', 'target': 'staff-pay'},
            {'say': 'Press Add Team Member. They can be given jobs straight away.',
             'page': r'^/staff/new$', 'start': '/staff/new', 'target': 'staff-save'},
        ],
    },
    {
        'key': 'import-team',
        'title': 'Import your whole team from a spreadsheet',
        'keywords': ['import team', 'import my team', 'import cleaners', 'upload team', 'spreadsheet',
                     'excel', 'csv', 'xlsx', 'bring my team', 'add my whole team'],
        'steps': [
            {'say': 'Open Team and press ⬆ Import my team (Excel or CSV).',
             'page': _TEAM, 'start': '/contractors/team', 'target': 'import-team'},
            {'say': 'Your file needs a heading row: Name (or First Name and Last Name) and Email, and if '
                    'you have them Phone and Pay, like "$20" an hour or "45%". Drag it in, or click to choose it.',
             'page': r'^/migration/team$', 'start': '/migration/team', 'target': 'import-file'},
            {'say': 'Press Import.',
             'page': r'^/migration/team$', 'start': '/migration/team', 'target': 'import-submit'},
            {'say': 'Each person is added and emailed an invite to set up their sign-in. Rows with no name '
                    'or email, or already on your team, are skipped and listed with the reason.',
             'page': r'^/migration/team$', 'start': '/migration/team'},
        ],
    },
    {
        'key': 'set-pay',
        'title': 'Set a cleaner\'s pay',
        'keywords': ['set pay', 'cleaner pay', 'pay rate', 'change pay', 'hourly rate', 'percentage',
                     'how much do i pay', 'pay not set', 'set her pay', 'set his pay'],
        'steps': [
            _open_cleaner(),
            {'say': 'In Pay Settings, pick the Pay Type (% of job price or Hourly) and type the Rate.',
             'page': _CLEANER, 'start': '/contractors/team', 'target': 'pay-settings'},
            {'say': 'Press Update Pay.',
             'page': _CLEANER, 'start': '/contractors/team', 'target': 'pay-update'},
            {'say': 'A job with hours on it pays those hours times your rate on Pricing, under Cleaner Pay '
                    '(open "Deposit, cleaner pay, bigger homes and add-ons"). Her own rate is used on jobs '
                    'without hours.',
             'page': r'^/settings/pricing$', 'start': '/settings/pricing', 'target': 'price-more'},
        ],
    },
    {
        'key': 'reschedule',
        'title': 'Reschedule a booking',
        'keywords': ['reschedule', 'move a booking', 'move a job', 'change the date', 'change date',
                     'change the time', 'new date', 'different day', 'postpone'],
        'steps': [
            _open_booking(),
            {'say': 'In The booking, open ✎ Change the job, date or time.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'change-job'},
            {'say': 'Change the Date and Time and press Save. Leave "Re-price this job to match" unticked '
                    'to keep the price.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'change-job-save'},
            {'say': 'Nobody is told by this. Let the customer and the cleaner know. Or drag the job to its '
                    'new day on the Calendar, which offers 📲 Tell them to text the cleaner.',
             'page': _BOOKING, 'start': '/bookings/'},
        ],
    },
    {
        'key': 'cancel-refund',
        'title': 'Cancel a booking or refund a deposit',
        'keywords': ['cancel', 'cancel a booking', 'cancel booking', 'cancel a job', 'refund',
                     'refund a deposit', 'refund deposit', 'give money back', 'customer cancelled'],
        'steps': [
            _open_booking(),
            {'say': 'Under Status & notes, set Status to Cancelled and press Save.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'booking-status'},
            {'say': 'Cancelling does not message anyone. Tell the customer and the cleaner yourself.',
             'page': _BOOKING, 'start': '/bookings/'},
            {'say': 'Akye has no refund button. Refund a card payment from your own Stripe dashboard, or pay '
                    'cash back yourself. The booking still shows the deposit as paid.',
             'page': _BOOKING, 'start': '/bookings/'},
            {'say': 'Moving, not cancelling, with no new date yet? Use ⏸️ Put this on hold in Less often '
                    'instead. Her deposit stays on the job.',
             'page': _BOOKING, 'start': '/bookings/'},
        ],
    },
    {
        'key': 'recurring',
        'title': 'Set up a recurring clean',
        'keywords': ['recurring', 'recurring clean', 'repeat', 'regular clean', 'every week', 'weekly',
                     'every two weeks', 'biweekly', 'monthly', 'standing appointment', 'set up a plan'],
        'steps': [
            _open_booking('Open Bookings and press the customer\'s name (or View) to open their first clean.'),
            {'say': 'In Less often, open 🔁 Recurring Cleaning.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'recurring-setup'},
            {'say': 'Choose How often, the Service, the First recurring cleaning date, the Price per visit '
                    'and the Arrival time.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'recurring-form'},
            {'say': 'Press 📅 Set up recurring cleaning. The visits go on your calendar, and this job stays '
                    'as it is.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'recurring-save'},
        ],
    },
    {
        'key': 'change-prices',
        'title': 'Change your prices',
        'keywords': ['change prices', 'change my prices', 'prices', 'price list', 'pricing', 'rates',
                     'raise prices', 'how much i charge', 'add-on prices', 'deep clean price'],
        'steps': [
            {'say': 'Open Pricing. Type what you charge for a standard clean of the house size shown and '
                    'press Fill in the rest.',
             'page': r'^/settings/pricing$', 'start': '/settings/pricing', 'target': 'price-anchor'},
            {'say': 'Change any price in the list.',
             'page': r'^/settings/pricing$', 'start': '/settings/pricing', 'target': 'price-grid'},
            {'say': 'Deep and move-out are worked out from the standard price. 1.6 means a deep clean '
                    'costs 60% more.',
             'page': r'^/settings/pricing$', 'start': '/settings/pricing', 'target': 'price-multipliers'},
            {'say': 'Add-ons, bigger homes, the deposit and cleaner pay are under "Deposit, cleaner pay, '
                    'bigger homes and add-ons".',
             'page': r'^/settings/pricing$', 'start': '/settings/pricing', 'target': 'price-more'},
            {'say': 'Press Save Pricing. New quotes and bookings and your booking page use the new prices; '
                    'bookings already made keep theirs.',
             'page': r'^/settings/pricing$', 'start': '/settings/pricing', 'target': 'price-save'},
        ],
    },
    {
        'key': 'cancellation-policy',
        'title': 'Change your cancellation policy or customer terms',
        'keywords': ['cancellation policy', 'cancellation', 'customer terms', 'terms', 'terms and conditions',
                     'policy', 'payment terms', 'late cancel', 'lockout fee'],
        'steps': [
            {'say': 'Open Settings, then Business. Find 📜 Customer Service & Payment Terms and change the '
                    'wording. Wrap a line in **stars** to make it a heading.',
             'page': r'^/settings/business$', 'start': '/settings/business', 'target': 'customer-terms'},
            {'say': 'Press Save Model Settings. The terms show on payment pages and invoices, from now on; '
                    'they do not reach back to bookings already made.',
             'page': r'^/settings/business$', 'start': '/settings/business', 'target': 'terms-save'},
            {'say': 'Your Booking Confirmation email also says deposits are non-refundable. To change it, '
                    'open Templates, then Emails, and edit Booking Confirmation.',
             'page': r'^/email-templates/?$', 'start': '/email-templates/'},
        ],
    },
    {
        'key': 'send-invoice',
        'title': 'Send an invoice',
        'keywords': ['send an invoice', 'send invoice', 'invoice', 'invoices', 'bill a customer', 'bill',
                     'email an invoice'],
        'steps': [
            _open_booking(),
            {'say': 'In Talk to the customer, under What do you want to send?, choose An invoice.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'send-kind'},
            {'say': 'Press 🧾 Send invoice. It is emailed with a link to view and pay it. Every invoice is '
                    'listed under Bookings, then Invoices.',
             'page': _BOOKING, 'start': '/bookings/', 'target': 'send-invoice'},
        ],
    },
    {
        'key': 'earnings',
        'title': 'See what you made this month',
        'keywords': ['what i made', 'how much did i make', 'earnings', 'income', 'revenue', 'profit',
                     'this month', 'money in', 'p&l', 'profit and loss'],
        'steps': [
            {'say': 'On your Dashboard, Money in is what came in this month and Kept is what is left after '
                    'pay, fees and expenses. Press Kept for the detail.',
             'page': r'^/$', 'start': '/', 'target': 'dash-money'},
            {'say': 'Profit & Loss counts money on the day it arrived: Money in, Money out and Net profit.',
             'page': r'^/money/pnl$', 'start': '/money/pnl', 'target': 'pnl-headline'},
            {'say': 'To see another month, a quarter or the year, change Show and Month and press Show.',
             'page': r'^/money/pnl$', 'start': '/money/pnl', 'target': 'pnl-period'},
        ],
    },
    {
        'key': 'invite-cleaners',
        'title': 'Invite cleaners to sign in and see their jobs',
        'keywords': ['invite cleaners', 'invite a cleaner', 'cleaner login', 'cleaner sign in', 'sign in',
                     'log in', 'login for cleaners', 'see their jobs', 'their schedule', 'app for cleaners'],
        'steps': [
            _open_cleaner(),
            # The box needs her agreement_token, which import, Hiring and the
            # offer give her and + Add someone directly does not (2026-10-25).
            {'say': 'Under No sign-in set up yet, press Resend invite email, or copy the link and text it to her. '
                    'That box is on cleaners you imported or hired through Hiring; one added with + Add someone '
                    'directly does not have it yet, so ask Akye support to send hers.',
             'page': _CLEANER, 'start': '/contractors/team', 'target': 'join-invite'},
            {'say': 'She opens it, chooses a password and sees her schedule and job offers. Cleaners you '
                    'import are emailed this invite for you.',
             'page': _CLEANER, 'start': '/contractors/team'},
        ],
    },

    # ── Commercial ─────────────────────────────────────────────────────────
    # Find leads -> call sheet -> walkthrough -> quote -> account -> jobs.
    # There is no spreadsheet import for commercial leads: Find new searches
    # Google, and Add one types a business in. (Leads, then Missed contacts,
    # imports a Google Ads export, but those are residential follow-up texts.)
    {
        'key': 'find-commercial-leads',
        'title': 'Find commercial leads (businesses to call)',
        'keywords': ['find businesses', 'find commercial leads', 'commercial leads', 'find leads',
                     'businesses to clean', 'offices to clean', 'search for businesses', 'lead finder',
                     'find new', 'prospects', 'prospecting', 'property managers', 'b2b leads',
                     'add a business', 'add a lead', 'janitorial leads', 'commercial'],
        'steps': [
            {'say': 'Open Commercial, then Find leads, and press 🎯 Find new.',
             'page': _LEADS, 'start': '/find-leads/', 'target': 'leads-tab-find'},
            {'say': 'Pick Who do you want to call?, leave Calling for which brand? on "Work it out from the '
                    'kind of business", type Where? as a city and state, and press 🎯 Find Businesses.',
             'page': _LEADS, 'start': '/find-leads/?view=find', 'target': 'find-form'},
            {'say': 'Untick any you do not want and press ➕ Add selected to call list. They land in Calls '
                    'as a first call due today. Ones already on your list show ✓ added.',
             'page': _LEADS, 'start': '/find-leads/?view=find'},
            {'say': 'Met one yourself or got a referral? Press ➕ Add one, type the business name and what you '
                    'know, and press ➕ Add to my call list.',
             'page': _LEADS, 'start': '/find-leads/?view=add', 'target': 'add-lead-form'},
        ],
    },
    {
        'key': 'call-sheet',
        'title': 'Call your commercial leads (the call sheet)',
        'keywords': ['call sheet', 'call list', 'calling', 'cold call', 'cold calling', 'start calling',
                     'call the next', 'log a call', 'log the call', 'follow-up date',
                     'follow up date', 'callback', 'outcome', 'todays calls', "today's calls"],
        'steps': [
            {'say': 'Open Commercial. On 📞 Calls, press Start calling → (or Call the next 20 →).',
             'page': _LEADS, 'start': '/find-leads/', 'target': 'start-calling'},
            {'say': 'The next business due is on screen, with your call script under it. Press the 📞 button to '
                    'ring them.',
             'page': _CALL, 'start': '/find-leads/call', 'target': 'call-phone'},
            {'say': 'No answer or Left a message? Press it. The next try is put on your calls for you and the '
                    'next business opens.',
             'page': _CALL, 'start': '/find-leads/call', 'target': 'call-quick'},
            {'say': 'Spoke to someone? Press Spoke to someone and fill in who it was, their email, when their '
                    'contract ends and what they said.',
             'page': _CALL, 'start': '/find-leads/call', 'target': 'call-spoke'},
            {'say': 'Press what they said: Booked a walkthrough 🎉 (put its date in "If they agreed to a '
                    'walkthrough, when?"), They asked for info, Call me back, We\'re under contract, Use us as '
                    'backup or Don\'t call again. The follow-up and its date are set for you.',
             'page': _CALL, 'start': '/find-leads/call', 'target': 'call-outcomes'},
            {'say': 'To pick the follow-up date yourself, open "Set the follow-up date yourself" and fill in What '
                    'needs doing next and When before you press what they said.',
             'page': _CALL, 'start': '/find-leads/call', 'target': 'call-followup'},
        ],
    },
    {
        'key': 'commercial-walkthrough',
        'title': 'Record a walkthrough of a business',
        'keywords': ['walkthrough', 'walk through', 'walk-through', 'site visit', 'site walk',
                     'measure the building', 'book a walkthrough', 'walkthrough checklist',
                     'ready to quote', 'hand to the owner'],
        'steps': [
            _open_lead(),
            {'say': 'In 🚶 Walkthrough, choose the day under Book it for and the Time, and press 📅 Book '
                    'walkthrough. It becomes their next step and shows on your Calendar.',
             'page': _LEAD, 'start': '/find-leads/?view=everyone', 'target': 'walk-book'},
            {'say': 'On site, open "Fill in the checklist on site": square feet, restrooms, how often, hours a '
                    'visit, what they want cleaned, and one row per surface under Work areas.',
             'page': _LEAD, 'start': '/find-leads/?view=everyone', 'target': 'walk-checklist'},
            {'say': 'Press 💾 Save the walkthrough. Their next step becomes "Write and send the quote", due '
                    'today, and the Walkthrough card shows a starting price once there is enough to price it.',
             'page': _LEAD, 'start': '/find-leads/?view=everyone', 'target': 'walk-checklist'},
            {'say': 'When a Sales login saves the walkthrough, or presses ✅ Ready to quote — hand to the owner, '
                    'it is handed to you: you are emailed and it shows under 📝 Ready to quote on Commercial. '
                    'Press 📝 Write the quote from this walkthrough to price it.',
             'page': _LEAD, 'start': '/find-leads/?view=everyone'},
        ],
    },
    {
        'key': 'commercial-quote',
        'title': 'Send a commercial quote',
        'keywords': ['commercial quote', 'send a commercial quote', 'contract quote', 'proposal',
                     'send a proposal', 'bid', 'office quote', 'quote a business', 'janitorial quote',
                     'commercial proposal'],
        'steps': [
            _open_lead('Open Commercial, press 🏢 Everyone and press the business\'s name. (No lead? Open '
                       'Commercial, then Quotes, and press + New Quote.)'),
            {'say': 'Press 📝 Contract quote. What you know about them and their walkthrough is filled in.',
             'page': _LEAD, 'start': '/find-leads/?view=everyone', 'target': 'lead-contract-quote'},
            {'say': 'Check Contact Info. Contact Person and Email are needed to send it.',
             'page': r'^/quotes/new$', 'start': '/quotes/new', 'target': 'cq-contact'},
            {'say': 'Under Work Areas & Line Items, add each area and its lines, or under Pricing & Schedule '
                    'set Service Frequency, Contract Term and the Price per Visit or Monthly Total.',
             'page': r'^/quotes/new$', 'start': '/quotes/new', 'target': 'cq-pricing'},
            {'say': 'Press 👁 Save & review before sending →. Nothing is sent yet.',
             'page': r'^/quotes/new$', 'start': '/quotes/new', 'target': 'cq-review'},
            {'say': 'Read the email they will get and fix anything under Before it goes out, then press 📨 Looks '
                    'right — send. They accept or decline online; accepted, they become a commercial account.',
             'page': r'^/quotes/\d+/review$', 'start': '/quotes/', 'target': 'cq-send'},
        ],
    },
    {
        'key': 'commercial-account',
        'title': 'Turn a business into a commercial account',
        'keywords': ['commercial account', 'make them an account', 'convert to account', 'won the contract',
                     'they said yes', 'new commercial customer', 'add a commercial account',
                     'commercial customer', 'turn a lead into a customer', 'convert a lead'],
        'steps': [
            _open_lead(),
            {'say': 'Press 🎉 Make them an account.',
             'page': _LEAD, 'start': '/find-leads/?view=everyone', 'target': 'lead-make-account'},
            {'say': 'Fill in what you agreed: Contact person, Email (for invoices), How often, Billing per month '
                    'or per visit, and the Amount.',
             'page': r'^/commercial/convert/\d+$', 'start': '/find-leads/?view=everyone', 'target': 'convert-form'},
            {'say': 'Press 🎉 Create commercial account. The business is marked won on your calls, with nothing '
                    'left due.',
             'page': r'^/commercial/convert/\d+$', 'start': '/find-leads/?view=everyone', 'target': 'convert-save'},
            {'say': 'A quote they accept online makes the account for you. A business that was never on your '
                    'calls? Open Commercial, then Accounts, and use ➕ Add a commercial account by hand.',
             'page': _ACCOUNTS, 'start': '/commercial/', 'target': 'account-add'},
        ],
    },
    {
        'key': 'commercial-booking',
        'title': 'Book a job for a commercial account',
        # No "book" or "job" in these: those words are book-job's, and "how do
        # I book a job" has to stay there. The title and steps carry them.
        'keywords': ['commercial account', 'office clean', 'clean an office', 'commercial clean',
                     'schedule a commercial clean', 'invoice a business', 'commercial invoice',
                     'net 30', 'scope of work', 'account visit'],
        'steps': [
            {'say': 'Open Commercial, then Accounts, and press Open on the business.',
             'page': _ACCOUNTS, 'start': '/commercial/', 'target': 'accounts-list'},
            {'say': 'Press 📅 Book a job. The contact and address are filled in from the account.',
             'page': _ACCOUNT, 'start': '/commercial/', 'target': 'account-book'},
            {'say': 'Under The Job, check the square footage and How often, and tick the Scope of work. The '
                    'customer and the cleaner both see it.',
             'page': r'^/commercial/\d+/book$', 'start': '/commercial/', 'target': 'cbook-scope'},
            {'say': 'Type the Price per visit, or press 💡 Suggest a price from the square footage. Estimated '
                    'hours is what the cleaner\'s pay is built from.',
             'page': r'^/commercial/\d+/book$', 'start': '/commercial/', 'target': 'cbook-price'},
            {'say': 'Under Schedule, choose the Date and Time.',
             'page': r'^/commercial/\d+/book$', 'start': '/commercial/', 'target': 'cbook-when'},
            {'say': 'Under Payment, pick a card link (deposit or full payment) or an invoice (sent now, or the '
                    'morning of the job), and press ✅ Book this job. Then give it to a cleaner.',
             'page': r'^/commercial/\d+/book$', 'start': '/commercial/', 'target': 'cbook-pay'},
        ],
    },

    # ── Hiring ─────────────────────────────────────────────────────────────
    # Two guides: getting applicants in, then interview to hire. One would be
    # nine steps. The order is the app's: video interview, approve (which
    # sends the conditional offer and the background check link), they
    # accept and join Team, then clearing the check marks them Hired.
    {
        'key': 'hiring',
        'title': 'Hire cleaners: get them to apply',
        'keywords': ['hire a cleaner', 'hire cleaners', 'hiring', 'hire', 'apply link', 'application link',
                     'hiring page', 'job application', 'applications', 'applicants', 'recruit',
                     'find cleaners', 'post a job', 'indeed', 'job ad'],
        'steps': [
            {'say': 'Open Hiring. Press Copy on "Your public application link" and post it with your job ad on '
                    'Indeed (as the external apply link), Facebook, Nextdoor or Craigslist, or text it to someone. '
                    'Job adverts to post, under Hiring, has adverts written for you.',
             'page': _APPS, 'start': '/contractors/applications', 'target': 'apply-link'},
            {'say': 'Applications land in this list. Anyone without cleaning experience or their own '
                    'transportation is turned down politely for you; everyone else is emailed a video '
                    'interview link about ten minutes later.',
             'page': _APPS, 'start': '/contractors/applications', 'target': 'applications-list'},
            {'say': 'Press Review to open an application. The box at the top says what to do next.',
             'page': _APPS, 'start': '/contractors/applications', 'target': 'applications-list'},
            {'say': 'Added someone by hand with + Add Applicant? Press 🎥 Send Interview Link (English & Spanish) '
                    'on their application.',
             'page': _APP, 'start': '/contractors/applications', 'target': 'app-send-interview'},
        ],
    },
    {
        'key': 'hire-cleaner',
        'title': 'Interview, background check and hire an applicant',
        'keywords': ['interview', 'video interview', 'watch interview', 'approve applicant', 'hire applicant',
                     'make an offer', 'conditional offer', 'offer letter', 'background check',
                     'bg check', 'clear background check', 'onboard'],
        'steps': [
            {'say': 'Open Hiring, then Interviews, and press ▶ Review next to someone whose interview is completed.',
             'page': r'^/admin/interviews/?$', 'start': '/admin/interviews', 'target': 'interviews-list'},
            {'say': 'Watch their answers. If you want them, press ✓ Approve Video — Request Background Check. '
                    'They are emailed your conditional offer with a link for their background check.',
             'page': r'^/admin/interviews/\d+$', 'start': '/admin/interviews', 'target': 'interview-approve'},
            {'say': 'When they accept the offer, they are added to your Team and get their onboarding page: the '
                    'work agreement, payment setup and start date.',
             'page': r'^/admin/interviews/\d+$', 'start': '/admin/interviews'},
            {'say': 'When their background check comes in, open their application. In Background Check, set '
                    'Status to ✅ Cleared and press Save Background Check. They are marked Hired.',
             'page': _APP, 'start': '/contractors/applications', 'target': 'app-bgcheck'},
            {'say': 'Skipping the video for someone you trust? Press 💌 Send Conditional Offer Email on their '
                    'application instead.',
             'page': _APP, 'start': '/contractors/applications', 'target': 'app-send-offer'},
        ],
    },

    # ── Getting set up ─────────────────────────────────────────────────────
    {
        'key': 'import-customers',
        'title': 'Import your customers from a spreadsheet',
        'keywords': ['import customers', 'import clients', 'import my customers', 'import my clients',
                     'bring my clients', 'bring my customers', 'bring my clients over', 'move my customers',
                     'customer list', 'client list', 'upload customers', 'upload clients',
                     'migration toolbox', 'migration', 'switch from', 'move from', 'transfer my customers'],
        'steps': [
            {'say': 'Open Settings, then Migration Toolbox, and press Import clients.',
             'page': r'^/migration/?$', 'start': '/migration/', 'target': 'import-clients'},
            {'say': 'Save your list as a CSV with a heading row: name and email are needed; phone, address, city, '
                    'zip and notes are optional. A history column is kept as a note, not turned into jobs.',
             'page': r'^/migration/clients$', 'start': '/migration/clients', 'target': 'clients-example'},
            {'say': 'For a recurring customer, add frequency (weekly, biweekly or monthly) and next_date written '
                    'like 2026-11-03. Their visits go on your calendar as pending, with no price or cleaner yet.',
             'page': r'^/migration/clients$', 'start': '/migration/clients', 'target': 'clients-example'},
            {'say': 'Drag the file in, or click to choose it, and press Import.',
             'page': r'^/migration/clients$', 'start': '/migration/clients', 'target': 'clients-file'},
            {'say': 'Each customer is added. Rows with no name or email, or already a customer, are skipped and '
                    'listed with the reason. Past jobs are not brought over.',
             'page': r'^/migration/clients$', 'start': '/migration/clients'},
        ],
    },
    {
        'key': 'add-customer',
        'title': 'Add a customer',
        'keywords': ['add a customer', 'add customer', 'new customer', 'add a client', 'add client',
                     'new client', 'create a customer', 'add someone i clean for',
                     # Without these, "find a client" went to the commercial lead finder.
                     'find a customer', 'find a client', 'look up a customer'],
        'steps': [
            {'say': 'Open Clients. Looking for one you have? Type in the search box. To add one, press '
                    '+ Add customer.',
             'page': r'^/bookings/clients/?$', 'start': '/bookings/clients', 'target': 'add-customer'},
            {'say': 'Type their Name. Phone, email, address and notes can wait; email is needed to send them '
                    'an invoice or receipt.',
             'page': r'^/bookings/clients/new$', 'start': '/bookings/clients/new', 'target': 'customer-name'},
            {'say': 'Press Add customer. Their page opens, ready to book them a job.',
             'page': r'^/bookings/clients/new$', 'start': '/bookings/clients/new', 'target': 'customer-save'},
        ],
    },
]


def by_key(key):
    return next((g for g in GUIDES if g['key'] == key), None)


def start_url(guide):
    """Where "Show me" opens: the first step's page, with the tour on."""
    first = (guide.get('steps') or [{}])[0]
    base = first.get('start') or '/'
    return f'{base}{"&" if "?" in base else "?"}tour={guide["key"]}'


def as_text(guide):
    """The guide as Nana reads it: a title and numbered steps."""
    lines = [f'{guide["title"]}, step by step:']
    for i, st in enumerate(guide['steps'], 1):
        lines.append(f'{i}. {st["say"]}')
    return '\n'.join(lines)


def public(guide):
    """What the page's tour script needs, and nothing else."""
    return {'key': guide['key'], 'title': guide['title'],
            'steps': [{'say': s['say'], 'page': s.get('page') or '',
                       'start': s.get('start') or '', 'target': s.get('target') or ''}
                      for s in guide['steps']]}


def validate():
    """Problems with the guides themselves, as sentences. Empty when sound."""
    problems, seen = [], set()
    for g in GUIDES:
        if g['key'] in seen:
            problems.append(f'{g["key"]}: key used twice')
        seen.add(g['key'])
        if not re.fullmatch(r'[a-z0-9-]+', g['key']):
            problems.append(f'{g["key"]}: key must be lowercase letters, digits and dashes')
        if not g.get('steps'):
            problems.append(f'{g["key"]}: no steps')
        for i, st in enumerate(g.get('steps') or [], 1):
            try:
                rx = re.compile(st.get('page') or '')
            except re.error:
                problems.append(f'{g["key"]} step {i}: page is not a valid pattern')
                continue
            start = (st.get('start') or '').split('?')[0]
            if not start.startswith('/') or start.startswith('//'):
                problems.append(f'{g["key"]} step {i}: start must be a path on this site')
            # A step on one particular record (a booking, a cleaner) starts from
            # the list it is opened from; any other step starts on its own page.
            elif st.get('page') and r'\d' not in st['page'] and not rx.search(start):
                problems.append(f'{g["key"]} step {i}: start {start} is not a page the step matches')
    return problems
