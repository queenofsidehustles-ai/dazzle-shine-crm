"""The blog, as data rather than as a wall of markup.

Same shape as guide.py and for the same reason: the index, the post page and
the structured data all come from one list, so they cannot drift.

## Why this exists

The guide answers the question somebody types months before they know cleaning
software exists. It works, and it is one page. A blog is the same idea repeated
-- one page per question a cleaning-business owner actually asks -- and the
compounding only happens if posts keep arriving.

## House rules for anything added here

**No villain.** The enemy is paperwork, never a person. These posts do not
suggest that owners exploit their cleaners, that cleaners cheat their owners,
or that anybody is the problem. The problem is that the work of remembering
things does not scale, and people are left doing it at eleven at night.

**Sell the time back, not the features.** An owner does not want software. They
want the two hours an evening that the software gives back.

**Say the real number.** A post that says "many owners" where it could say "the
third job of the day" is a post nobody finishes.
"""

# Newest first. `date` is the publication date as an ISO string, used for the
# index order and the structured data; it is not parsed anywhere that would
# break if a future one were added.
POSTS = [
    {
        'slug': 'the-jobs-you-lose-without-noticing',
        'title': 'The jobs you lose without noticing',
        'date': '2026-10-06',
        'dek': ('Nobody rings to tell you they booked someone else. The work '
                'leaks out through four gaps, and none of them look like '
                'problems on the day.'),
        'sections': [
            {
                'id': 'the-quote-never-sent',
                'h': 'The quote you meant to send that evening',
                'body': [
                    'Somebody rings at eleven in the morning while you are on '
                    'your knees under a sink. You take their number on the '
                    'back of a receipt and promise a price by the end of the '
                    'day. By the end of the day there are two more jobs, a '
                    'cleaner who needs collecting, and a receipt that is now '
                    'in the wrong trouser pocket.',
                    'They do not ring back to complain. They ring the next '
                    'company on the list, and you never learn that you lost '
                    'anything. This is the most expensive thing that happens '
                    'in a cleaning business and it leaves no trace at all.',
                    'The fix is not working harder in the evening. It is that '
                    'the quote goes out while you are still standing in their '
                    'kitchen, at the price you said out loud, and the price '
                    'they were told is the price they can book at.',
                ],
            },
            {
                'id': 'the-follow-up',
                'h': 'The follow-up nobody has time for',
                'body': [
                    'Most people who ask for a price do not say no. They say '
                    'nothing. They meant to reply, then the week happened to '
                    'them exactly as it happened to you.',
                    'A single message four days later recovers a surprising '
                    'share of those. Not a clever message -- "still thinking '
                    'about it?" is enough, because the answer is usually yes. '
                    'The reason it does not get sent is not that owners do not '
                    'know it works. It is that remembering which eleven people '
                    'need it, on which day, is a job in itself.',
                ],
            },
            {
                'id': 'the-money-you-did-not-invoice',
                'h': 'The job that got cleaned and never got billed',
                'body': [
                    'This one is worse than losing a lead, because you already '
                    'paid for it. The cleaner went, the supplies went, the '
                    'drive happened, and three weeks later the invoice is '
                    'still a thing you have been meaning to do.',
                    'Owners rarely lose track of a big job. They lose track of '
                    'the ordinary ones -- the second clean for a customer who '
                    'usually pays by standing order, the extra hour nobody '
                    'wrote down, the one-off somebody squeezed in. Each is '
                    'small enough to forget and they do not stop arriving.',
                ],
            },
            {
                'id': 'who-did-what',
                'h': 'Who actually did the work',
                'body': [
                    'When the schedule lives in your head and a phone, pay day '
                    'becomes an act of reconstruction. Who covered the Tuesday '
                    'when somebody was ill. Whether the deep clean took the '
                    'four hours it was quoted at or the six it really took. '
                    'Which of two cleaners with the same first name did the '
                    'job on Oak Street.',
                    'Nobody is being dishonest. The record simply was not kept '
                    'at the time, and a week later everybody involved is '
                    'remembering in good faith and remembering differently. '
                    'That is a paperwork failure, not a people failure, and it '
                    'is fixed by the job recording itself as it happens rather '
                    'than by anybody being more careful.',
                ],
            },
            {
                'id': 'what-this-is-worth',
                'h': 'What closing these is actually worth',
                'body': [
                    'Add up one lost quote a week, one unbilled job a month, '
                    'and the hour every Sunday spent working out what happened '
                    'during the week. For most small cleaning businesses that '
                    'is more than the cost of any software they are weighing '
                    'up, and it is paid whether or not they buy anything.',
                    'The point is not the features. It is that you stop being '
                    'the part of the system that has to remember.',
                ],
            },
        ],
    },
    {
        'slug': 'remote-help-and-cleaners-on-the-ground',
        'title': 'Remote help and cleaners on the ground',
        'date': '2026-10-06',
        'dek': ('A cleaning business hires two completely different kinds of '
                'people, and the mistake is managing them the same way.'),
        'sections': [
            {
                'id': 'two-jobs',
                'h': 'They are not the same job',
                'body': [
                    'Every cleaning business that grows past the owner ends up '
                    'with two kinds of people. There are cleaners, who are in '
                    'somebody else\'s house doing the work. And there is '
                    'office help -- answering the phone, chasing quotes, '
                    'booking jobs, nudging invoices -- which does not need to '
                    'happen in your town, or in your time zone.',
                    'Owners often hire the second kind long after they needed '
                    'to, because the first kind feels like the real business. '
                    'But the hours that pile up at eleven at night are almost '
                    'never cleaning hours.',
                ],
            },
            {
                'id': 'what-remote-needs',
                'h': 'What remote help actually needs from you',
                'body': [
                    'Access, and a boundary. Somebody answering your phone '
                    'needs to see the calendar, the prices and the customer '
                    'history, or they cannot answer anything without ringing '
                    'you -- which costs you more than doing it yourself.',
                    'What they should not see is everybody\'s pay, your '
                    'margins, or your bank details. "Give them the logins" is '
                    'how most owners start and it is why most owners stop. The '
                    'answer is a login of their own that opens the parts of '
                    'the business they work in and nothing else.',
                    'Write down what they are allowed to decide without '
                    'asking. A quote under a certain figure. A reschedule '
                    'inside the same week. Without that, every judgement call '
                    'comes back to you and you have hired an extra inbox '
                    'rather than help.',
                ],
            },
            {
                'id': 'what-cleaners-need',
                'h': 'What cleaners on the ground actually need',
                'body': [
                    'The opposite. A cleaner does not want access to the '
                    'business; they want today to be unambiguous. The address, '
                    'the time, the door code, what this particular customer '
                    'cares about, and what counts as finished.',
                    'Most friction between owners and cleaners is not about '
                    'money or effort. It is that the cleaner was told one '
                    'thing in a voice note on Tuesday and the customer '
                    'expected another. A checklist attached to the job settles '
                    'it in advance, for both of them, and it is the single '
                    'cheapest thing an owner can do to stop complaints.',
                    'The second thing they need is to know what they will be '
                    'paid and when, without asking. An owner who answers that '
                    'question clearly keeps people far longer than one who '
                    'pays slightly more and leaves it vague.',
                ],
            },
            {
                'id': 'where-it-goes-wrong',
                'h': 'Where it goes wrong',
                'body': [
                    'The usual failure is one system stretched over both. The '
                    'cleaners are in a group chat, the office help is in the '
                    'same group chat, and the customer\'s door code is '
                    'somewhere in it along with a photograph of somebody\'s '
                    'lunch.',
                    'Split them. What a cleaner sees is one job at a time. '
                    'What office help sees is the pipeline. What you see is '
                    'both. Nobody has to be trusted less for this to be true '
                    '-- it is simply easier to do a job well when the thing in '
                    'front of you is the job.',
                ],
            },
        ],
    },
    {
        'slug': 'what-to-pay-a-cleaner',
        'title': 'What to pay a cleaner, and how to say it',
        'date': '2026-10-06',
        'dek': ('Percentage, hourly or per job — each one changes behaviour. '
                'Pick the one that matches the work you want done.'),
        'sections': [
            {
                'id': 'three-ways',
                'h': 'Three ways, and what each one encourages',
                'body': [
                    'Hourly is the easiest to explain and the hardest to '
                    'scale: it pays for time present, so a slow clean costs '
                    'you more than a fast one and nobody is rewarded for '
                    'getting good at the job.',
                    'Per job is the opposite. It pays for the clean, so '
                    'getting quicker is worth something -- and if you price a '
                    'job badly, somebody is underpaid for four hours and will '
                    'remember it.',
                    'A percentage of what the job sold for is the one most '
                    'growing businesses settle on. It survives you putting '
                    'prices up, it makes a big job worth more to the person '
                    'doing it, and it is one sentence to explain.',
                ],
            },
            {
                'id': 'say-it-out-loud',
                'h': 'Say the number before they start',
                'body': [
                    'Whatever you choose, the thing that keeps cleaners is '
                    'that they knew the figure before the job rather than '
                    'after it. Pay disputes almost never start with somebody '
                    'thinking they were cheated. They start with two people '
                    'who never said a number out loud and then disagreed about '
                    'what was obvious.',
                    'Put it on the job. If it is attached to the work itself, '
                    'nobody is reconstructing it from memory on pay day and '
                    'nobody has to ask.',
                ],
            },
            {
                'id': 'raises',
                'h': 'Decide in advance what earns a raise',
                'body': [
                    'The quickest way to lose somebody good is to have no '
                    'answer when they ask what it would take to earn more. '
                    'Pick the bar before anybody asks -- a number of completed '
                    'jobs, a rating that holds, turning up reliably -- and say '
                    'it when you hire.',
                    'It costs nothing, and it turns a conversation you dread '
                    'into one you have already had.',
                ],
            },
        ],
    },
]

# The long-form guide is part of this blog as far as a reader is concerned, but
# it keeps its own URL: it is indexed, it ranks, and moving an address that
# already works to tidy up a menu is how a page stops being found.
ANCHOR = {
    'slug': None,
    'endpoint': 'marketing.guide',
    'title': 'How to Start a Cleaning Business',
    'date': '2026-09-09',
    'dek': ('The whole thing, start to first paying customer — what it costs, '
            'how to price, and the one decision that gets new owners fined.'),
}

TITLE = 'The Akye blog'
SUBTITLE = ('Written for people who run cleaning businesses — what the work '
            'actually costs, where it leaks, and how other owners handle it.')


def find(slug):
    """One post by slug, or None. Used by the post route."""
    for p in POSTS:
        if p['slug'] == slug:
            return p
    return None


def index_entries():
    """Everything the index lists, newest first, the anchor guide included."""
    rows = [dict(p, endpoint=None) for p in POSTS]
    rows.append(dict(ANCHOR))
    rows.sort(key=lambda r: r['date'], reverse=True)
    return rows


def structured_data(post, product_name, url):
    """Schema.org for one post, built from the same dict the page renders."""
    return {
        '@context': 'https://schema.org',
        '@type': 'BlogPosting',
        'headline': post['title'],
        'description': post['dek'],
        'datePublished': post['date'],
        'dateModified': post['date'],
        'mainEntityOfPage': {'@type': 'WebPage', '@id': url},
        'author': {'@type': 'Organization', 'name': product_name},
        'publisher': {'@type': 'Organization', 'name': product_name},
    }
