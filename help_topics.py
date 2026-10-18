"""Owner-facing help for Nana: how Akye works, in the words an owner would use.

Hand-written from the code on 2026-10-18. Nana repeats these to paying
customers, so every sentence has to be true of the app as it is. When a
feature changes, change its topic here in the same commit. Links must be real
pages an owner can open.
"""

TOPICS = [
    # ── Getting started ────────────────────────────────────────────────────
    {
        'key': 'getting-started',
        'title': 'Getting started: the setup steps',
        'keywords': ['getting started', 'setup', 'set up', 'start', 'new account', 'first steps',
                     'onboarding', 'checklist', 'begin', 'where do i start'],
        'answer': ('Open Getting started and work down the list in order: add your business details, '
                   'check your prices, share your booking page, add a cleaner, add a customer, then '
                   'schedule a job and assign it. Each step has a button that takes you to the right '
                   'page, and it ticks itself off once it is done. Add yourself as the cleaner if you '
                   'are still doing the cleaning. Already have a team or a customer list? You can import '
                   'them instead of typing them in.'),
        'link': ('Getting started', '/settings/getting-started'),
    },
    {
        'key': 'setup-chat',
        'title': 'The setup chat on Getting started',
        'keywords': ['setup chat', 'chat', 'nana setup', 'help me set up', 'assistant setup',
                     'fill in for me', 'conversation'],
        'answer': ('When it is switched on, the owner sees a chat with Nana on the Getting started page. '
                   'She asks one question at a time and can fill in your business details, suggest a full '
                   'price list from what you charge for a 2 bed / 2 bath standard clean, add a cleaner and '
                   'add a customer. Nothing is saved until you press Save on the card she shows you. She '
                   'will not touch bank or card details, passwords or anything that moves money; for those '
                   'she points you to the page and you type it yourself.'),
        'link': ('Getting started', '/settings/getting-started'),
    },
    {
        'key': 'business-details',
        'title': 'Business details, branding and text alerts',
        'keywords': ['business name', 'phone', 'address', 'logo', 'branding', 'colors', 'colours',
                     'brand', 'tagline', 'time zone', 'alerts', 'owner alert', 'business settings'],
        'answer': ('Go to Settings, then Business. Enter your business name, phone, email, address, website '
                   'and time zone exactly as you want customers to see them, because they appear on quotes, '
                   'invoices and emails. The branding card sets your header and button colours and your email '
                   'tagline, which your booking page uses too. Put your mobile in "Text alerts to" so you get a '
                   'text when a cleaner or customer texts in; if you leave it blank, alerts go to your business phone number instead. Replies always land in Messages.'),
        'link': ('Business settings', '/settings/business'),
    },
    {
        'key': 'customer-terms',
        'title': 'Your customer terms',
        'keywords': ['terms', 'customer terms', 'cancellation policy', 'policy', 'terms and conditions',
                     'lockout', 'payment terms'],
        'answer': ('Your customer terms are on Settings, then Business. They come as an editable starting '
                   'draft covering things like cancellations, cards on file and our cleaners, and they are '
                   'shown on payment pages and printed on invoices. They are yours to change and they are not '
                   'legal advice, so read them and adjust anything that does not match how you work. Changes '
                   'apply from when a customer sees them; they do not reach back to bookings already made.'),
        'link': ('Business settings', '/settings/business'),
    },

    # ── Prices ─────────────────────────────────────────────────────────────
    {
        'key': 'prices',
        'title': 'Setting your prices',
        'keywords': ['price', 'prices', 'pricing', 'price list', 'rates', 'how much', 'charge',
                     'deep clean', 'move out', 'move-out', 'multiplier', 'bedroom', 'bathroom'],
        'answer': ('Go to Pricing. Type what you charge for a standard clean of a 2 bed / 2 bath house and '
                   'press "Fill in the rest" to get a suggested price for every house size, then change any '
                   'box you like. Deep clean and move-out are worked out from the standard price using a '
                   'multiplier, so 1.6 means a deep clean costs 60% more; you keep one list instead of three. '
                   'Every quote, booking and your booking page use these prices. Saving the page ticks '
                   'the prices step off Getting started.'),
        'link': ('Pricing', '/settings/pricing'),
    },
    {
        'key': 'add-ons',
        'title': 'Add-ons and bigger homes',
        'keywords': ['add-on', 'addon', 'extras', 'oven', 'fridge', 'windows', 'cabinets', 'laundry',
                     'square feet', 'sq ft', 'sqft', 'bigger home', 'large house'],
        'answer': ('On Pricing, the Add-ons section sets the price of each extra (inside oven, inside fridge, '
                   'laundry, inside windows, inside cabinets) and how long it takes. The time is added to the '
                   'job so your cleaner is paid for the extra work. The Bigger Homes section charges per 200 '
                   'sq ft over the standard size for that bedroom count, and adds time to the job as well.'),
        'link': ('Pricing', '/settings/pricing'),
    },
    {
        'key': 'recurring-discounts',
        'title': 'Recurring discounts',
        'keywords': ['recurring discount', 'weekly discount', 'biweekly', 'monthly discount', 'frequency',
                     'discount for regulars', 'percent off'],
        'answer': ('Recurring customers get a built-in discount off the price: 5% for monthly, 10% for every '
                   'two weeks and 15% for weekly. One-time cleans have no discount. The discount comes out of '
                   'your side, not your cleaner\'s pay, because cleaner pay is worked out from the hours in '
                   'the job rather than the price.'),
        'link': ('Pricing', '/settings/pricing'),
    },
    {
        'key': 'deposits',
        'title': 'Deposits',
        'keywords': ['deposit', 'deposits', 'down payment', 'hold my spot', 'booking fee', 'not confirmed'],
        'answer': ('Set your booking deposit on Pricing, under Deposit; the emails, texts and payment page '
                   'all use that amount. It goes toward the total, it is not an extra charge. When a '
                   'customer books through your booking page, the booking stays pending and they are emailed'
                   ' and texted a link to pay the deposit; paying it confirms the booking and saves their '
                   'card for the balance. When you create a booking yourself you can choose to send a '
                   'deposit link, a full payment link, or nothing.'),
        'link': ('Pricing', '/settings/pricing'),
    },
    {
        'key': 'discount-codes',
        'title': 'Discount codes',
        'keywords': ['discount code', 'promo code', 'coupon', 'promo', 'code'],
        'answer': ('Create codes on the Discounts page. A code can take a percentage or a fixed dollar amount '
                   'off, and you can give it a maximum number of uses and an expiry date. You can switch a code '
                   'off at any time by editing it.'),
        'link': ('Discounts', '/discounts/'),
    },

    # ── Booking page, quotes, bookings ─────────────────────────────────────
    {
        'key': 'booking-page',
        'title': 'Your booking page and how to share it',
        'keywords': ['booking page', 'book online', 'online booking', 'booking link', 'share', 'website',
                     'embed', 'widget', 'facebook', 'instagram', 'link in bio'],
        'answer': ('You already have a booking page where customers pick what they want cleaned, see your '
                   'price straight away, choose a date and book themselves. Open Your booking page to copy '
                   'the link and put it in your Facebook or Instagram bio, your Google Business Profile, your '
                   'email signature, or texts to people who ask for a price. If you have a website, the paid '
                   'plans give you one line to paste in so the form appears inside your own site. Tick the box '
                   'on that page once you have shared it.'),
        'link': ('Your booking page', '/settings/booking-page'),
    },
    {
        'key': 'online-booking-flow',
        'title': 'What happens when a customer books online',
        'keywords': ['customer booked', 'new booking', 'online booking', 'pending', 'tentative', 'booking request'],
        'answer': ('A booking from your booking page lands in Bookings as pending, and the customer is saved '
                   'in Clients. They are emailed and texted that it is not confirmed until the deposit is paid, '
                   'with a link to pay it, and you get an email about the tentative booking. Once the deposit is '
                   'paid the booking is confirmed and they get a receipt. Then assign a cleaner.'),
        'link': ('Bookings', '/bookings/'),
    },
    {
        'key': 'create-booking',
        'title': 'Creating a booking yourself',
        'keywords': ['create booking', 'new booking', 'add booking', 'book a job', 'schedule a job',
                     'phone booking', 'add a job'],
        'answer': ('Press New booking for customers who book by phone, text or in person. Fill in the customer, '
                   'service, house size, extras, date and time; the price fills in from your price list unless '
                   'you type your own. Choose whether to send a deposit link, a full payment link, or collect '
                   'later, and whether to send a booking confirmation. After saving, assign a cleaner on the '
                   'job page. To book someone you already clean for, press Book again on their client page so '
                   'their details come with them.'),
        'link': ('New booking', '/bookings/new'),
    },
    {
        'key': 'residential-quotes',
        'title': 'Sending a quote',
        'keywords': ['quote', 'quotes', 'estimate', 'send a quote', 'price quote', 'quoting'],
        'answer': ('From Leads, choose to quote someone, fill in what they want and send it. The quote is '
                   'emailed, and you can tick to text it too. The customer opens their quote, picks a date and '
                   'books at exactly the price you quoted, then pays the deposit to confirm. You can also send a '
                   'copy to a second person, such as a homeowner, from the lead\'s page, or convert a lead to a '
                   'booking yourself.'),
        'link': ('Quote a customer', '/leads/quote/new'),
    },
    {
        'key': 'customers',
        'title': 'Customers (clients)',
        'keywords': ['customer', 'customers', 'client', 'clients', 'add customer', 'customer list'],
        'answer': ('Clients lists everyone you clean for. Customers who book online or through a quote are '
                   'added automatically, and bookings you create by hand are linked to a client too. Use Add '
                   'customer to enter one yourself, or import a whole list from the Migration Toolbox. A client\'s '
                   'page shows their jobs, their portal link, and a Book again button that carries their '
                   'details across.'),
        'link': ('Clients', '/bookings/clients'),
    },
    {
        'key': 'recurring-cleans',
        'title': 'Recurring cleans',
        'keywords': ['recurring', 'repeat', 'regular', 'weekly', 'every two weeks', 'biweekly', 'monthly',
                     'series', 'plan', 'standing appointment', 'stop recurring'],
        'answer': ('On a job\'s page, use the Recurring Cleaning card to choose every week, every 2 weeks or once '
                   'a month, then schedule it. Future visits are added to your calendar ahead of time and kept '
                   'topped up. A monthly plan can repeat on the same date or on the same weekday, like the 2nd '
                   'Wednesday. For a deep clean followed by regular cleans, start a separate plan from the '
                   'one-off job with its own service, price and start date. You can stop a plan, or move every '
                   'future visit to a different cleaner, from the same card.'),
        'link': ('Bookings', '/bookings/'),
    },
    {
        'key': 'calendar',
        'title': 'The calendar and moving a job',
        'keywords': ['calendar', 'schedule', 'reschedule', 'move a job', 'change date', 'drag', 'month view'],
        'answer': ('The Calendar shows the month with each day\'s jobs in time order. Drag a job to another day '
                   'to move it. Moving a job does not text anyone by itself, so you can rearrange a week freely; '
                   'when the job has a cleaner you are offered a one-click way to tell them the new date.'),
        'link': ('Calendar', '/bookings/calendar'),
    },
    {
        'key': 'hold-cancel',
        'title': 'Putting a job on hold or cancelling',
        'keywords': ['hold', 'on hold', 'pause', 'cancel', 'cancelled', 'postpone', 'no date'],
        'answer': ('If a customer needs to move but does not know when, use "Put this on hold" on the job page '
                   'instead of cancelling. A held job is taken off every reminder and automatic charge, its money '
                   'is left untouched, and the assigned cleaner is texted not to go. When there is a new date, put '
                   'it back on from the same card. To cancel for good, change the status to Cancelled.'),
        'link': ('Bookings', '/bookings/'),
    },

    # ── Dispatch and team ──────────────────────────────────────────────────
    {
        'key': 'assign-cleaner',
        'title': 'Assigning a cleaner to a job',
        'keywords': ['assign', 'assign cleaner', 'send job', 'give job', 'dispatch', 'who is cleaning',
                     'unassigned', 'work order'],
        'answer': ('Open the job and use the "Who\'s doing it" card. Pick a cleaner under Assign to, set her '
                   'pay (leave it blank for the usual share), keep "Send the work order now" ticked and '
                   'press Assign & send. She is emailed and texted the address, her pay and the checklist. '
                   'Your dashboard warns you about jobs tomorrow with nobody on them.'),
        'link': ('Bookings', '/bookings/'),
    },
    {
        'key': 'job-board',
        'title': 'Offering a job to the team (first to claim)',
        'keywords': ['offer to team', 'job board', 'open job', 'claim', 'broadcast job', 'first to claim',
                     'release job', 'crew job', 'team job'],
        'answer': ('On the job page, choose "Offer it to the whole team" under Assign to in the "Who\'s doing'
                   ' it" card and press Assign & send, or press the megaphone button next to the job on '
                   'Bookings. Every active cleaner with a phone number gets a text with the date, area, '
                   'service and their pay, plus a personal claim link. The first to claim gets the job and '
                   'is sent the checklist, and you get a text. Anyone whose day would clash with another job'
                   ' is blocked from claiming. For a job needing 2 or more cleaners, the first ones to claim'
                   ' fill the spots. If a cleaner releases a job, it is offered to the team again.'),
        'link': ('Bookings', '/bookings/'),
    },
    {
        'key': 'add-team',
        'title': 'Adding cleaners to your team',
        'keywords': ['add cleaner', 'new cleaner', 'team member', 'staff', 'employee', 'contractor',
                     'deactivate', 'remove cleaner', 'team'],
        'answer': ('Use Add a cleaner to enter their name, phone and email. Give each person a different name, '
                   'adding a surname or initial if two share a first name, because pay is matched by name. '
                   'Cleaners do not need a login to work: they get texted and emailed links to their jobs, '
                   'their day and their checklists. Deactivating someone stops all job offers and notifications '
                   'to them without telling them.'),
        'link': ('Add a cleaner', '/staff/new'),
    },
    {
        'key': 'team-logins',
        'title': 'Team logins and roles',
        'keywords': ['login', 'logins', 'user', 'users', 'role', 'roles', 'permissions', 'access',
                     'office manager', 'va', 'dispatcher', 'admin', 'invite'],
        'answer': ('Settings, then Team logins, is where the owner gives someone their own sign-in. Enter '
                   'their name and email and pick a role: Limited (can read bookings), Cleaner (their '
                   'assigned work only), Dispatcher (bookings and scheduling), Sales (finding and working '
                   'leads only), Admin (operations but no finance or pay), or Owner (full access). They get '
                   'an invite link and choose their own password. You can disable a login or send a password'
                   ' reset link from the same page.'),
        'link': ('Team logins', '/logins/'),
    },
    {
        'key': 'import',
        'title': 'Importing your team or customer list',
        'keywords': ['import', 'migration', 'csv', 'spreadsheet', 'upload list', 'move from', 'switch from',
                     'bring my customers', 'transfer'],
        'answer': ('The Migration Toolbox takes a CSV file. For your team, use columns name, email and phone; '
                   'each person is added and emailed a link to set up their own sign-in. For customers, use '
                   'name and email, plus phone, address, city, zip and notes if you have them. Add frequency '
                   '(weekly, biweekly or monthly) and next_date (written like 2026-11-03) and a recurring plan '
                   'is put on the calendar as pending for you to review. Rows missing a name or email, or '
                   'already in the system, are skipped and listed with the reason. Past job history is not imported.'),
        'link': ('Migration Toolbox', '/migration/'),
    },
    {
        'key': 'availability',
        'title': 'Team availability and messaging the whole team',
        'keywords': ['availability', 'who can work', 'schedule team', 'message team', 'broadcast',
                     'text everyone', 'group text'],
        'answer': ('Under Team, Availability texts each active cleaner a personal link for a week; they tap the '
                   'days they can work and the answers show up as a grid, including who has not replied. '
                   '"Message the team" sends one message to everyone, or to the people you pick, by text, '
                   'email or both.'),
        'link': ('Availability', '/team/availability'),
    },

    # ── Hiring ─────────────────────────────────────────────────────────────
    {
        'key': 'hiring-overview',
        'title': 'How hiring works',
        'keywords': ['hire', 'hiring', 'applicant', 'apply', 'application', 'recruit', 'job posting',
                     'indeed', 'apply link', 'job ad'],
        'answer': ('Your apply page link is shown on the Applications page, and "Job adverts to post" gives you '
                   'ready-made adverts to post free on Indeed, Facebook groups or Craigslist, with the right '
                   'version for contractors or employees. Applicants can apply in English or Spanish from their '
                   'phone. Someone with no cleaning experience or no transportation gets a polite automatic '
                   'rejection; everyone else is sent a video interview link about ten minutes later. A cleaning company that applies skips the interview and is held for you to review their insurance. Applicants '
                   'who stall are followed up automatically.'),
        'link': ('Applications', '/contractors/applications'),
    },
    {
        'key': 'video-interviews',
        'title': 'Video interviews',
        'keywords': ['video interview', 'interview', 'record', 'questions', 'review interview', 'screening'],
        'answer': ('Qualified applicants get a link to record short video answers to six questions, in English or '
                   'Spanish, from their phone with no app needed. Watch them on the Interviews page; Spanish '
                   'answers are shown with an English translation. Approve to send a conditional offer with a '
                   'background check step, or reject to send a polite email. You can resend the interview link '
                   'or preview the offer email before it goes.'),
        'link': ('Interviews', '/admin/interviews'),
    },
    {
        'key': 'hiring-settings',
        'title': 'Hiring settings: background checks, phone interviews, test cleans',
        'keywords': ['background check', 'bg check', 'phone interview', 'calendly', 'test clean',
                     'trial clean', 'shadow', 'uniform', 'hiring settings'],
        'answer': ('Hiring settings holds your interview calendar link, used by the Send Interview Invite button, '
                   'and your background check provider\'s name and link. Applicants pay the provider and upload '
                   'their results privately; marking the check as cleared on their application moves them to '
                   'Hired. You can also require a test clean, with what you pay and how long it runs, so the '
                   'offer says so up front; pay for it and book it as an ordinary job. Turn on uniforms to ask new '
                   'hires their shirt size.'),
        'link': ('Hiring settings', '/contractors/hiring-settings'),
    },
    {
        'key': 'new-hire-onboarding',
        'title': 'Onboarding a new cleaner and the work agreement',
        'keywords': ['onboarding', 'agreement', 'contract', 'sign', 'w-9', 'w9', 'id', 'new hire',
                     'paperwork', 'non-solicitation', 'non solicitation', 'poaching'],
        'answer': ('When someone accepts your offer they become a team member and get one onboarding page: sign '
                   'the work agreement, set up how they get paid, choose a pay schedule and start date, send a '
                   'photo ID and W-9, and read the training guide. The built-in agreement matches the worker type set in Settings, Business (1099 contractor or W-2 employee), though the onboarding page itself still says contractor agreement and asks for a W-9 either way. The contractor version includes a '
                   '24-month non-solicitation clause with a $2,000 buyout, and your customer terms ask customers '
                   'not to hire your cleaners directly. You can replace the wording with your own; it is not legal advice.'),
        'link': ('Business settings', '/settings/business'),
    },

    # ── On the job ─────────────────────────────────────────────────────────
    {
        'key': 'checklists-photos',
        'title': 'Cleaner checklists and before/after photos',
        'keywords': ['checklist', 'checklists', 'work order', 'photos', 'before and after', 'pictures',
                     'on my way', 'sign off', 'cleaning checklist', 'tasks'],
        'answer': ('Each job\'s cleaner gets a checklist link. They tap On My Way, which texts and emails the '
                   'customer, then Clock In, tick off each task, add at least one before and one after photo, '
                   'and Clock Out. If the customer is home they can sign off and leave a star rating. Submitting the photos marks the job completed and emails you. To also send the customer a review request, set the job to Completed yourself on the job page. Photos are kept private. Edit what is on '
                   'each service\'s list on the Cleaning Checklist page.'),
        'link': ('Cleaning Checklist', '/workorders/templates'),
    },
    {
        'key': 'time-tracking',
        'title': 'Time tracking',
        'keywords': ['time', 'clock in', 'clock out', 'hours', 'timesheet', 'time tracking', 'punch'],
        'answer': ('Cleaners paid by the hour see Clock in and Clock out buttons on their daily job page, and the '
                   'checklist\'s clock fills in the hours worked on a job. The Timesheet shows hours per cleaner '
                   'for each week. It is a record of who worked when; it does not work out overtime or breaks, '
                   'so give it to whoever runs your payroll.'),
        'link': ('Timesheet', '/contractors/timesheet'),
    },

    # ── Paying cleaners ────────────────────────────────────────────────────
    {
        'key': 'cleaner-pay',
        'title': 'How cleaner pay is worked out',
        'keywords': ['cleaner pay', 'pay rate', 'how much do cleaners make', 'labor rate', 'hourly rate',
                     'split', 'crew pay', 'pay per job'],
        'answer': ("Set what you pay per hour on Pricing, under Cleaner Pay. A job's pay is its hours times "
                   "that rate, shared between whoever is on it, so a discount never cuts your cleaner's pay."
                   ' On the job page, the "Who\'s doing it" card shows each person\'s pay, which you can type '
                   'over and save with Save pay; the number of cleaners and the hours are under "How this '
                   'pay is worked out". Each job keeps the rate it was quoted at; unpaid jobs offer a Re-'
                   'rate button if you change your rate.'),
        'link': ('Pricing', '/settings/pricing'),
    },
    {
        'key': 'payroll-payouts',
        'title': 'Paying your cleaners and Stripe payouts',
        'keywords': ['payroll', 'pay cleaners', 'payout', 'payouts', 'stripe connect', 'direct deposit',
                     'zelle', 'venmo', 'cash', 'tips', 'paid'],
        'answer': ('Payroll lists each cleaner\'s completed jobs for the week and what is still owed. Pay a job by '
                   'Stripe, or record that you paid by cash, Zelle, Venmo, check or bank transfer, and the '
                   'cleaner is told. A job cannot be paid twice. Stripe payouts need your Stripe connected and the '
                   'cleaner to finish "Set up how you get paid" from their onboarding page; you are emailed when '
                   'they are ready. Type a tip share on the payroll row if there is one.'),
        'link': ('Payroll', '/contractors/payroll'),
    },
    {
        'key': 'tax-forms',
        'title': '1099s and W-9s',
        'keywords': ['1099', 'w-9', 'w9', 'tax form', 'taxes', 'contractor taxes', 'year end'],
        'answer': ('The 1099 & W-9 page shows what each cleaner was paid in a year, flags anyone at or over $600, '
                   'and shows whether you have their W-9 on file. It does not file anything for you; take it to '
                   'your accountant.'),
        'link': ('1099 & W-9', '/money/tax-forms'),
    },

    # ── Taking money ───────────────────────────────────────────────────────
    {
        'key': 'connect-stripe',
        'title': 'Connecting Stripe to take card payments',
        'keywords': ['stripe', 'connect stripe', 'card payments', 'api key', 'keys', 'test mode',
                     'live mode', 'connections', 'get paid by card'],
        'answer': ('Card payments go to your own Stripe account, straight to your bank. Create a Stripe account, '
                   'then in Stripe go to Developers, API keys, copy the publishable and secret keys and paste them '
                   'into Settings, Connections. Test keys let you try everything without charging real cards; swap '
                   'in live keys when you are ready. Press "Test Stripe connection" and check it names your '
                   'business. On Akye, texting, email and job photos are provided for you (lead search depends on your plan), so Stripe is the one thing you connect.'),
        'link': ('Connections', '/settings/connections'),
    },
    {
        'key': 'taking-payments',
        'title': 'Taking payments, payment links and invoices',
        'keywords': ['payment', 'take payment', 'payment link', 'invoice', 'invoices', 'qr code', 'mark paid',
                     'collect', 'balance', 'receipt'],
        'answer': ('On the job page, the "Talk to the customer" card is where you choose what to send: a '
                   'payment link goes by email and text, an invoice by email. The Money card has Take '
                   'Payment, which opens the card page with a QR code the customer can scan, and Mark paid '
                   'for cash or other payments, with the date the money arrived and an optional receipt. You'
                   ' can also record a deposit paid outside Stripe. Paid jobs have a receipt you can print '
                   'or save. Tips added on the payment page are kept separate for the cleaner.'),
        'link': ('Invoices', '/invoices/'),
    },
    {
        'key': 'charge-balances',
        'title': 'Charging the balance automatically',
        'keywords': ['charge balance', 'auto charge', 'autopay', 'card on file', 'charge card', 'balance due',
                     'automatic payment'],
        'answer': ('In Settings, Automations, choose how balances are collected: charge the card on file on the '
                   'day at the job\'s start time, show them as owed without charging (the starting setting), or '
                   'never charge from here. A card is on file when the customer paid a deposit or saved one in '
                   'their portal. Held jobs are never charged.'),
        'link': ('Automations', '/settings/automations'),
    },
    {
        'key': 'refunds-chargebacks',
        'title': 'Refunds, chargebacks and price corrections',
        'keywords': ['refund', 'refunds', 'chargeback', 'dispute', 'wrong price', 'correct price', 'overcharged'],
        'answer': ('There is no refund button in Akye; refunds are done from your own Stripe dashboard. For a '
                   'chargeback, open the job and use "Chargeback evidence pack", which gathers the booking, '
                   'payment, every message sent and the cleaner\'s photos, and lets you record who was on site. '
                   'If a booking went out at the wrong price, use "Correct price & notify customer" on the job page.'),
        'link': ('Bookings', '/bookings/'),
    },

    # ── Customers after the job ────────────────────────────────────────────
    {
        'key': 'customer-portal',
        'title': 'The customer portal',
        'keywords': ['portal', 'customer portal', 'customer login', 'self service', 'save card',
                     'customer account', 'book again'],
        'answer': ('Each customer has a private portal link, shown on their client page, where you can also '
                   'preview and send a welcome email (send a test to yourself first). They confirm who they are '
                   'with their ZIP code or the last 4 digits of their phone. The portal shows upcoming cleanings, '
                   'history and invoices, lets them save a card for automatic billing, and lets them ask for '
                   'another clean, which comes to you as a lead and an email.'),
        'link': ('Clients', '/bookings/clients'),
    },
    {
        'key': 'reviews-ratings',
        'title': 'Ratings, reviews and your Google review link',
        'keywords': ['review', 'reviews', 'rating', 'ratings', 'google review', 'stars', 'feedback from customers'],
        'answer': ('When you change a job\'s status to Completed on the job page (not when a cleaner\'s photo submission or Nana marks it finished), the customer is emailed and '
                   'texted a link to rate it, unless you ticked "Don\'t ask this customer for a review". People '
                   'who give 4 or 5 stars see a Leave a Google Review button and can add a tip; below 4 stars, you '
                   'are emailed so you can make it right. Add your Google review link in Settings, Business; with '
                   'no link, the button is hidden. Unrated requests get one reminder after a few days.'),
        'link': ('Business settings', '/settings/business'),
    },

    # ── Messages and automations ───────────────────────────────────────────
    {
        'key': 'messages',
        'title': 'Texting and email with customers and cleaners',
        'keywords': ['message', 'messages', 'text', 'texting', 'sms', 'inbox', 'reply', 'email',
                     'sent log', 'templates', 'did it send'],
        'answer': ('Messages is one inbox of text conversations with cleaners, applicants and customers; replies to '
                   'your number land there. Text templates save wording you use often. The Sent log shows every '
                   'text and email the system has sent and flags any that failed. Texting is not included on the '
                   'free plan; email always works.'),
        'link': ('Messages', '/messages/'),
    },
    {
        'key': 'automations',
        'title': 'Automations: reminders and follow-ups',
        'keywords': ['automation', 'automations', 'reminder', 'reminders', 'follow up', 'follow-up',
                     'drip', 'win back', 'digest', 'morning digest', 'automatic'],
        'answer': ('Settings, Automations, lets you switch each one on or off: day-before reminders (customers and '
                   'cleaners separately), charging balances, follow-ups and win-backs (thank-yous, review reminders, '
                   'morning-of notes and pay links), lead follow-up emails, applicant follow-ups, rental calendar '
                   'checks, follow-up texts to missed callers, subcontractor insurance warnings, and a morning '
                   'digest email. The digest starts off; the rest start on, and balances start on show-as-owed. '
                   'The page also shows when each one last ran.'),
        'link': ('Automations', '/settings/automations'),
    },

    # ── Getting customers ──────────────────────────────────────────────────
    {
        'key': 'leads',
        'title': 'Leads and enquiries',
        'keywords': ['lead', 'leads', 'enquiry', 'inquiry', 'website lead', 'new enquiries', 'convert lead'],
        'answer': ('Leads holds enquiries: quote requests from your website, people you quoted by phone, and '
                   'requests from the customer portal. Mark each one new, contacted, converted or lost, and convert '
                   'it to a booking from its page. Website leads who have not booked get follow-up emails while '
                   'that automation is on.'),
        'link': ('Leads', '/leads/'),
    },
    {
        'key': 'missed-contacts',
        'title': 'Following up missed calls and price requests',
        'keywords': ['missed call', 'missed contacts', 'google ads', 'local services', 'lsa', 'follow-up texts',
                     'never booked', 'voicemail'],
        'answer': ('Under Leads, Missed contacts lets you add a phone number by hand or import a Google Ads leads '
                   'export. Start the sequence and they get three texts, on day 0, day 4 and day 8, worded either '
                   'for a missed call or for someone who asked for a price. Texts stop if they book or reply STOP. '
                   'Edit the wording on Follow-up texts; every message must keep its "Reply STOP" line.'),
        'link': ('Missed contacts', '/leads/lsa/'),
    },
    {
        'key': 'commercial-leads',
        'title': 'Finding commercial leads and outreach emails',
        'keywords': ['commercial', 'find leads', 'prospect', 'prospects', 'property manager', 'office',
                     'cold call', 'outreach', 'call list', 'b2b', 'janitorial'],
        'answer': ('Commercial, then Find leads, searches for businesses by type and city and adds them to your '
                   'call list. Today shows who is due a call; the call sheet puts the script on screen, and you log '
                   'each outcome to set the next step. Some outcomes start a short email follow-up, like three '
                   'emails after you send information. Outreach emails must come from your own domain, a one-time '
                   'setup under Settings, Sending domain. Won businesses become commercial accounts.'),
        'link': ('Find leads', '/find-leads/'),
    },
    {
        'key': 'commercial-quotes',
        'title': 'Commercial quotes and pricing',
        'keywords': ['commercial quote', 'proposal', 'bid', 'commercial pricing', 'contract', 'per visit',
                     'monthly price', 'square footage'],
        'answer': ('Commercial, then Quotes, creates a proposal with the property, services, frequency, contract '
                   'term and price per visit or per month, and emails it. The customer accepts or declines online; '
                   'an accepted quote becomes a commercial account and you are emailed. Unanswered quotes are '
                   'followed up on days 2, 5 and 9. The price helper builds prices from your cleaner cost, target '
                   'labor share, minimum per visit and drive time, which you set in Commercial Pricing.'),
        'link': ('Quotes', '/quotes/'),
    },
    {
        'key': 'sending-domain',
        'title': 'Sending email from your own domain',
        'keywords': ['domain', 'sending domain', 'email domain', 'dns', 'from address', 'spam'],
        'answer': ('By default your email goes out from a shared address with your business name on it, which is '
                   'fine for customers who know you. To email businesses who have never heard of you, add your '
                   'domain under Settings, Sending domain, put the three records it shows into your DNS, and press '
                   'Check. DNS changes can take a few hours to show.'),
        'link': ('Sending domain', '/settings/sending-domain'),
    },
    {
        'key': 'rentals',
        'title': 'Short-term rental turnovers',
        'keywords': ['airbnb', 'vrbo', 'rental', 'rentals', 'turnover', 'turnovers', 'ical', 'vacation rental',
                     'short-term rental', 'checkout'],
        'answer': ('Under Rentals, add a property with the calendar link the listing publishes (on Airbnb, '
                   'Availability, then Export calendar). Every check-out becomes a cleaning job on that date at '
                   'your usual start time and price, and same-day turnovers, where the next guest arrives that day, '
                   'are flagged. The calendars are re-read daily, or press sync on a property to read it now.'),
        'link': ('Rentals', '/rentals/'),
    },

    # ── Money ──────────────────────────────────────────────────────────────
    {
        'key': 'reports-money',
        'title': 'Profit, expenses and reports',
        'keywords': ['profit', 'p&l', 'pnl', 'money', 'revenue', 'income', 'expenses', 'report', 'reports',
                     'how much did i make', 'job economics', 'export'],
        'answer': ('Money shows Profit & Loss counted on the day money actually arrived, plus cleaner pay once it '
                   'is paid. Add costs on Expenses, including receipts and monthly costs that post themselves. Job '
                   'economics shows which jobs make money and what discounts cost you, and Trends shows the last '
                   'few months. The P&L downloads as a spreadsheet for your accountant, and Settings, Export data, '
                   'downloads your customers, jobs and workers.'),
        'link': ('Profit & Loss', '/money/pnl'),
    },

    # ── Language ───────────────────────────────────────────────────────────
    {
        'key': 'spanish',
        'title': 'Spanish and translation',
        'keywords': ['spanish', 'espanol', 'translate', 'translation', 'language', 'bilingual', 'english'],
        'answer': ('Set a cleaner\'s language to Spanish on their profile and their job pages show in Spanish. Job board offers, schedule changes, pay updates, availability requests and team messages are translated; job assignments, work orders and day-before reminders still go in English. In a Messages conversation, switch on '
                   'Spanish translation: you type English, they get Spanish, and their replies show in English. '
                   'Applicants can apply and record their interview in Spanish, and you see an English translation.'),
        'link': ('Team', '/contractors/team'),
    },

    # ── Nana, account, help ────────────────────────────────────────────────
    {
        'key': 'nana',
        'title': 'What Nana can and cannot do',
        'keywords': ['nana', 'assistant', 'ai', 'ask nana', 'chatbot', 'what can you do', 'voice', 'microphone'],
        'answer': ('Ask Nana about your business in your own words, such as what is booked tomorrow, what came in '
                   'last month or what is owed. Every figure comes from your records. She drafts emails for you to '
                   'copy, and can offer to mark a job finished, turn on the morning digest, or send one outreach '
                   'email to one commercial prospect, but only after you read it and press the button. She never '
                   'texts anyone and never charges a card. You can ask out loud with the microphone, but not while '
                   'driving. The page shows how many questions are left this month.'),
        'link': ('Ask Nana', '/ask'),
    },
    {
        'key': 'plan-trial',
        'title': 'Your plan and free trial',
        'keywords': ['plan', 'trial', 'free trial', 'billing', 'subscription', 'upgrade', 'locked', 'padlock',
                     'cancel subscription', 'card on file for akye'],
        'answer': ('A new account gets a 30-day free trial with every feature, counted from the day you '
                   'sign up. Adding a cleaner and a customer does not change the date; it is just the '
                   'quickest way to see it work. '
                   'Your plan and the days left are shown on Billing and at the top of Settings, Business. A'
                   ' feature your plan does not include shows a lock and takes you to a page comparing '
                   'plans. If a trial ends without a paid plan, or a payment fails, you drop to the free '
                   'plan and keep all your data. Billing also has a link to update your card, see invoices '
                   'or cancel.'),
        'link': ('Billing', '/billing'),
    },
    {
        'key': 'account-security',
        'title': 'Your password and two-factor sign-in',
        'keywords': ['password', 'change password', 'forgot password', 'two factor', '2fa', 'security',
                     'authenticator', 'locked out'],
        'answer': ('Open Security in the sidebar to change your password or turn on two-factor sign-in with an '
                   'authenticator app, and to get backup codes. Forgot your password? Use the forgot password link '
                   'on the sign-in page. An owner can also send a teammate a reset link from Team logins.'),
        'link': ('Security', '/account'),
    },
    {
        'key': 'get-help',
        'title': 'Getting help or reporting a problem',
        'keywords': ['support', 'help', 'contact', 'problem', 'bug', 'broken', 'not working', 'report',
                     'feedback', 'faq'],
        'answer': ('Press the Feedback button, which is on every screen. Say what happened by typing or using the '
                   'microphone, and attach or capture a screenshot; the page you were on is sent with it so you do '
                   'not have to explain where you were. The FAQs page holds answers to problems people have already '
                   'hit, and you can add your own.'),
        'link': ('FAQs', '/faq/'),
    },
]
