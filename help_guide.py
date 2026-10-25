"""How Nana answers "how do I..." about Akye itself.

Nana knew the business -- jobs, money, customers -- and nothing about the
software she lives in. Asked how hiring works, she guessed. This gives her
something to look it up in, the same way she looks up last month's takings:

- help_topics.TOPICS, written by hand from the code. When a feature changes,
  its topic changes in the same commit.
- The FAQ entries this business has saved (Settings > FAQ), which are answers
  that already worked once for a real person.

The search is plain keyword matching on purpose. There are a few dozen topics,
the words owners use are predictable ("hire", "pay my cleaners"), and a match
anyone can read is easier to fix than one nobody can explain. Claude does the
understanding; this only has to put the right two or three topics in front of
her.
"""
import re

_WORD = re.compile(r"[a-z0-9']+")

# Words that say nothing about which topic was meant.
_STOP = {
    'a', 'an', 'the', 'i', 'my', 'me', 'to', 'do', 'how', 'can', 'is', 'are',
    'of', 'in', 'on', 'for', 'and', 'or', 'it', 'what', 'where', 'does',
    'with', 'you', 'your', 'we', 'our', 'be', 'get', 'when', 'there', 'this',
    'that', 'way', 'set', 'up', 'use', 'make', 'have', 'need', 'want', 'should',
    'would', 'could', 'will', 'akye', 'nana', 'please', 'help', 'about', 'which',
}


def _words(text):
    out = set()
    for w in _WORD.findall((text or '').lower()):
        if w in _STOP or len(w) < 2:
            continue
        out.add(w)
        # Crude plural/tense folding: "cleaners" finds "cleaner", "hiring" "hire".
        for suf in ('ing', 'es', 's', 'ed'):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                out.add(w[:-len(suf)])
    return out


def _topics():
    try:
        import help_topics
        topics = list(help_topics.TOPICS)
    except Exception:
        topics = []
    # This business's own FAQ, when there is a database to read.
    try:
        from models import Faq
        for f in Faq.query.limit(200).all():
            # The question is the keyword list: it is in the words somebody
            # in this business actually used, so it should win a close match.
            topics.append({'key': f'faq-{f.id}', 'title': f.question,
                           'keywords': [f.question], 'answer': f.answer, 'link': None})
    except Exception:
        pass
    return topics


def _score(topic, words):
    kw = set()
    for k in topic.get('keywords') or []:
        kw |= _words(k)
    title = _words(topic.get('title'))
    body = _words(topic.get('answer'))
    return 3 * len(words & kw) + 2 * len(words & title) + len(words & body)


def search(question, limit=3):
    """The topics most likely to answer this, best first."""
    words = _words(question)
    if not words:
        return []
    scored = [(_score(t, words), i, t) for i, t in enumerate(_topics())]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for _s, _i, t in scored[:limit]]


def guide_for(question):
    """The step-by-step guide (howto.py) this asks for, or None.

    A guide wins over a topic when it matches at least as well: steps in the
    words on the buttons are what somebody asking "how do I" wants, and only
    a guide can offer "Show me"."""
    import howto
    words = _words(question)
    if not words:
        return None
    best, best_score = None, 0
    for g in howto.GUIDES:
        sc = _score({'keywords': g['keywords'], 'title': g['title'],
                     'answer': ' '.join(s['say'] for s in g['steps'])}, words)
        if sc > best_score:
            best, best_score = g, sc
    if best is None:
        return None
    top = search(question, limit=1)
    if top and _score(top[0], words) > best_score:
        return None
    return best


def answer(question):
    """(text for the model, a (label, href) button or None)."""
    import howto
    g = guide_for(question)
    if g is not None:
        text = ('From the Akye step-by-step guide. Give these steps as a numbered '
                'list, in these words, and say they can press Show me to have the '
                'screen point at each button. Do not add steps that are not '
                'here:\n\n' + howto.as_text(g))
        return text, ('Show me', howto.start_url(g))
    found = search(question)
    if not found:
        return ('Nothing in the Akye help guide matches that. Say you are not '
                'sure, and suggest contacting Akye support rather than guessing.'), None
    parts = []
    for t in found:
        parts.append(f'{t["title"]}: {t["answer"]}')
    link = next((t['link'] for t in found if t.get('link')), None)
    text = ('From the Akye help guide (answer only from this; if it does not '
            'cover the question, say so):\n\n' + '\n\n'.join(parts))
    return text, link
