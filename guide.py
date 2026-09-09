"""The guide, as data rather than as a wall of markup.

Kept out of the template so the table of contents, the page itself and the
structured data all come from one list. Written by hand three times, they
drift, and the version search engines read is the one nobody looks at.

## Why this page exists

Somebody typing "how to start a cleaning business" is this product's buyer
several months before they know cleaning software exists. Answering the
question properly is how they arrive, and it keeps working while nobody is
watching it. That only holds if the answer is genuinely good -- a thin page
built for keywords ranks for a week and helps nobody.

## What it deliberately does not do

It does not give legal, tax or insurance advice, and it names no state. Rules
differ everywhere and change, and a page that pretends otherwise gets somebody
fined. Where the answer is "it depends where you are", it says so.
"""

TITLE = 'How to Start a Cleaning Business'
SUBTITLE = ('The whole thing, start to first paying customer — what it costs, '
            'how to price, and the one decision that gets new owners fined.')

# Written for the questions people actually type. A heading that matches a
# real search does more than a keyword stuffed into a paragraph.
SECTIONS = [
    {
        'id': 'what-it-costs',
        'h': 'What it actually costs to start',
        'body': [
            'Less than almost any other business, which is why so many people '
            'start one and why the ones that last are the ones that got the '
            'boring parts right.',
            'Most people start for somewhere between a few hundred and a couple '
            'of thousand dollars. The floor is supplies, a vacuum you are not '
            'ashamed of, registration fees and a year of insurance. Everything '
            'above that — a van, a website, staff — is a choice you can make '
            'later out of money the business earned.',
            'What you do not need on day one: an office, a logo somebody '
            'designed, a fleet, or employees. Those are what people buy '
            'instead of getting customers.',
        ],
    },
    {
        'id': 'residential-or-commercial',
        'h': 'Decide who you clean for first',
        'body': [
            'Homes or businesses. They look similar and they are different '
            'trades, and trying to do both at the start usually means being '
            'mediocre at each.',
            'Residential pays faster and starts easier. One person can begin '
            'this week, customers pay on the day, and a good clean sells the '
            'next one. The ceiling is your own hours until you hire.',
            'Commercial pays more per contract and takes longer to win. '
            'Offices, property managers, realtors and short-let hosts sign for '
            'months at a time and pay on terms, which is steadier money — but '
            'expect several conversations and a walkthrough before anyone '
            'signs, and expect to be asked for proof of insurance before they '
            'will talk seriously.',
            'A common path is to start residential for cash flow and work '
            'commercial in the gaps, because commercial is what makes the '
            'business worth something later.',
        ],
    },
    {
        'id': 'register-the-business',
        'h': 'Register the business',
        'body': [
            'You can trade as yourself, but almost everybody forms a limited '
            'liability company instead. The reason is in the name: if '
            'something goes wrong at a customer’s house, the claim is against '
            'the business rather than against your own house.',
            'It is usually a form, a fee and a day or two, and the fee varies '
            'a lot depending on where you are. You will also want a federal '
            'tax ID — free, applied for online — and a bank account in the '
            'business’s name. Do not run the business through your personal '
            'account: it makes tax time miserable and it weakens the '
            'protection you just paid for.',
            'Licensing is the part that genuinely differs. Some places require '
            'a general business licence and nothing else; others want a '
            'specific one for cleaning services. Check with your own state and '
            'city before you take money, not after.',
        ],
    },
    {
        'id': 'insurance',
        'h': 'Insurance and bonding',
        'body': [
            'This is the step people skip and the one that ends businesses.',
            'General liability covers the broken vase and the customer who '
            'slips on a wet floor. It is the policy commercial clients will ask '
            'to see before they sign, and many will not sign without it.',
            'A janitorial bond covers theft by whoever you send. It is cheap, '
            'and being bonded is worth saying out loud when you are asking '
            'somebody to trust you with their key.',
            'Workers’ compensation becomes a legal requirement once you employ '
            'people, and the threshold for "employ" is lower than most new '
            'owners assume. See the next section, because it is the same '
            'question wearing a different hat.',
        ],
    },
    {
        'id': 'contractors-or-employees',
        'h': 'Contractors or employees: the decision that gets people fined',
        'body': [
            'Every new cleaning company faces this and a lot of them get it '
            'wrong. Treating cleaners as 1099 contractors looks cheaper — no '
            'payroll tax, no workers’ compensation, no unemployment insurance '
            '— and it is the single most expensive mistake in this industry.',
            'The test is not what your paperwork says. It is how the work '
            'actually happens, and the rules differ between the federal '
            'government and your own state, with some states considerably '
            'stricter than the federal standard.',
            'Broadly, the more the answer is yes, the more likely somebody is '
            'an employee whatever the contract says: do you set their hours, '
            'do you tell them how to do the job rather than what result you '
            'want, do you supply the equipment and the products, do they wear '
            'your shirt, do they work only for you, is the work you give them '
            'the core of what your business sells?',
            'A genuine contractor generally runs their own business, works for '
            'other people too, brings their own kit, and is hired for an '
            'outcome rather than supervised through a task.',
            'If it is misclassified, the bill is back taxes, penalties and '
            'interest, and it lands years later when somebody files for '
            'unemployment or gets hurt. Plenty of cleaning companies run '
            'legitimately on contractors; plenty run on employees. Decide '
            'deliberately, and ask an accountant in your own state before you '
            'hire the first person rather than after the tenth.',
        ],
    },
    {
        'id': 'pricing',
        'h': 'How to price the work',
        'body': [
            'Price the job, not the hour. Customers want to know what it costs '
            'before you arrive, and quoting by the hour punishes you for '
            'getting faster at your own trade.',
            'Work out your number by starting from what you need to earn. Take '
            'the hourly rate you want, add what it costs to send somebody — '
            'their pay, the payroll cost on top of it, supplies, travel, a '
            'share of insurance — then add margin. Estimate the hours a job '
            'takes and quote a flat price from that. After twenty jobs you '
            'will know your own times better than any calculator.',
            'Charge more for the first clean of a new customer. A place nobody '
            'has deep cleaned in a year takes far longer than the visits after '
            'it, and quoting the recurring rate for it is how new owners end '
            'up working a ten-hour day for a three-hour price.',
            'Recurring work is usually priced a little under a one-off, '
            'because a booked calendar is worth something. Do not discount so '
            'far that your best customers are your worst-paying ones.',
            'Raise your prices before you are desperate. The customers who '
            'leave over a small increase are usually the ones costing you the '
            'most to keep.',
        ],
    },
    {
        'id': 'first-customers',
        'h': 'Getting the first customers',
        'body': [
            'The first ten come from people, not advertising. Tell everybody '
            'you know what you are doing now, and ask them to pass it on. It '
            'feels like the least professional option and it is the one that '
            'works.',
            'Then claim your free business listing on the major search '
            'engines. For a local service this matters more than a website: it '
            'is what makes you appear when somebody nearby searches for a '
            'cleaner, and it costs nothing but the time to verify it.',
            'Get reviews from the very first job, and ask on the day while '
            'they are standing in a clean house. Reviews are what a stranger '
            'uses to choose between you and somebody identical.',
            'Give people a way to book without phoning you. A page where '
            'somebody picks what they want, sees the price and books it will '
            'win jobs at nine at night that a phone number never would.',
            'For commercial, call. Property managers, realtors, offices and '
            'short-let hosts respond to a conversation, not an email, and the '
            'email is what you send after the call to the address they gave '
            'you.',
        ],
    },
    {
        'id': 'hiring',
        'h': 'When to hire, and what breaks',
        'body': [
            'Hire when you are turning work away or working every Saturday, '
            'not before. The first hire costs more than they earn for a while, '
            'and hiring early out of optimism is how new owners run out of '
            'cash.',
            'What breaks at two or three cleaners is not the cleaning. It is '
            'knowing who is where, whether they turned up, whether the job was '
            'done to your standard, and what you owe them at the end of the '
            'week. Those four questions eat an evening a week if you are '
            'tracking them on your phone.',
            'Pay per job rather than per hour where you can, so the cost of a '
            'job is known before it happens and getting faster is rewarded '
            'rather than punished. Whatever you choose, make it the same for '
            'everybody and write it down.',
        ],
    },
    {
        'id': 'running-it-remotely',
        'h': 'Running it without cleaning yourself',
        'body': [
            'The point of the business, for most people, is to stop being the '
            'one holding the mop. That is possible and plenty of owners do it, '
            'but only if you can answer the four questions above without being '
            'there.',
            'What makes it work is proof rather than trust. Cleaners marking a '
            'job started and finished, photographs of the work, a checklist '
            'the customer agreed to, and a record of what was paid. With those '
            'you can run crews in a city you are not standing in. Without '
            'them, every complaint is your word against somebody’s memory.',
            'This is also what makes the business sellable. A cleaning company '
            'that only works because the owner knows everything is a job. One '
            'that runs on written procedures and records is an asset.',
        ],
    },
    {
        'id': 'systems',
        'h': 'The systems worth having early',
        'body': [
            'Keep it to what a customer or a cleaner actually touches: a way '
            'to book, a way to be reminded, a way to pay, and a record of what '
            'happened on the job.',
            'You can start on a calendar and a notebook, and many people do. '
            'The point at which that stops working is usually the second or '
            'third cleaner, when the cost is no longer your time but the job '
            'nobody was assigned and the invoice nobody sent.',
        ],
    },
]

# The questions people type as questions. Answered plainly here and handed to
# search engines as structured data, which is how they end up shown directly.
FAQS = [
    ('Do I need an LLC to start a cleaning business?',
     'Not legally in most places — you can trade as a sole proprietor. Most '
     'people form one anyway, because it separates a claim against the '
     'business from a claim against their own home. Registration rules and '
     'fees differ by state, so check yours.'),
    ('How much does it cost to start a cleaning business?',
     'Commonly a few hundred to a couple of thousand dollars: supplies, '
     'equipment, registration and a year of insurance. It is one of the '
     'cheapest businesses to begin, which is why getting the boring parts '
     'right matters more than the money.'),
    ('Should my cleaners be 1099 contractors or W-2 employees?',
     'It depends on how the work actually happens, not on what the contract '
     'says. If you set their hours, direct how the work is done, supply the '
     'equipment and they work only for you, they usually count as employees. '
     'Some states are stricter than the federal rules. Misclassifying is the '
     'most expensive mistake in this industry — ask an accountant in your own '
     'state before you hire.'),
    ('What insurance does a cleaning business need?',
     'General liability at minimum, and commercial clients will usually ask '
     'to see it before signing. A janitorial bond covers theft. Workers’ '
     'compensation becomes a legal requirement once you have employees.'),
    ('How do I price cleaning jobs?',
     'Quote a flat price for the job rather than an hourly rate. Work back '
     'from the hourly rate you want, add the real cost of sending somebody, '
     'then add margin. Charge more for a first clean than for the recurring '
     'visits after it.'),
    ('How do I get my first cleaning customers?',
     'People first — tell everybody you know and ask them to pass it on. Then '
     'claim your free local business listing, ask for a review after every '
     'job, and give people a way to book online without phoning you. For '
     'commercial work, call and follow up by email afterwards.'),
    ('Can I run a cleaning business without cleaning myself?',
     'Yes, and most owners aim for it. It works when you can see who is where, '
     'whether they arrived, whether the work met your standard and what you '
     'owe them — without being on site. That takes records rather than trust.'),
]


def structured_data(product_name, url):
    """What search engines read, built from the same lists the page renders.

    In Python rather than in the template: three hand-written copies of this
    drift, and the one that drifts unnoticed is the one nobody looks at.
    """
    return {
        '@context': 'https://schema.org',
        '@graph': [
            {
                '@type': 'Article',
                'headline': TITLE,
                'description': SUBTITLE,
                'author': {'@type': 'Organization', 'name': product_name},
                'publisher': {'@type': 'Organization', 'name': product_name},
                'mainEntityOfPage': url,
            },
            {
                '@type': 'FAQPage',
                'mainEntity': [
                    {'@type': 'Question', 'name': q,
                     'acceptedAnswer': {'@type': 'Answer', 'text': a}}
                    for q, a in FAQS
                ],
            },
        ],
    }
