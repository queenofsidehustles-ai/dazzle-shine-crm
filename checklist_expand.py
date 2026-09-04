"""Turn "Everything in Standard Cleaning" into the actual list.

A deep-clean checklist opens with a line reading *Everything in Standard
Cleaning*, and a move-out one with *Everything in Deep Cleaning*. That is fine
shorthand for somebody who has done a hundred standard cleans. It is useless to
a cleaner whose first job is a deep clean: she is handed a reference to a list
she has never seen and cannot open, and the twelve things it stands for are the
twelve most basic things about the job.

Worse, it is silent. Nothing looks broken — there is just one line where twelve
should be, and the only way to find out is a customer complaining that the
floors were not mopped.

So a reference is expanded into the items it points at, following the chain as
far as it goes (move-out → deep → standard), and the expanded block is marked
with the name it came from so the cleaner's page can fold it up. A long list is
its own problem: forty items with no shape is a list people stop reading. Folded
by section, it is a job.
"""
import re

# Two wordings already exist in this codebase and neither knew about the other:
# the seeded templates say "Everything in Standard Cleaning", while the built-in
# work-order defaults say "All standard clean tasks". Owners edit both and will
# write a third. Matched loosely, by shape, rather than by exact string — a
# reference this misses is a checklist that silently loses twelve lines.
REFERENCES = (
    re.compile(r'^\s*everything\s+(?:else\s+)?in\s+(?:the\s+)?(.+?)\s*$', re.I),
    re.compile(r'^\s*all\s+(?:the\s+)?(.+?)\s+tasks\s*$', re.I),
)
# Deliberately no looser pattern than these two. "Includes deep dusting" is a
# real task on a real checklist, and a matcher greedy enough to catch every
# possible phrasing would swallow it and replace it with a whole other service.


def reference_phrase(item):
    """The service a line points at, as written, or None if it is a real task."""
    for pattern in REFERENCES:
        m = pattern.match(item)
        if m:
            return m.group(1)
    return None

# What a reference resolves to. Matched on the words in the phrase rather than an
# exact template name, because "Standard Cleaning", "the standard clean" and
# "Standard" all mean the same thing to whoever typed it.
SERVICE_WORDS = {
    'standard': 'standard',
    'deep': 'deep',
    'move': 'moveout',
    'moveout': 'moveout',
    'move-out': 'moveout',
    'airbnb': 'airbnb',
    'apartment': 'apartment',
    'luxury': 'luxury',
}


def service_for(phrase):
    """Which service a phrase like 'the Standard Cleaning' points at, or None."""
    words = re.split(r'[^a-z]+', (phrase or '').lower())
    for w in words:
        if w in SERVICE_WORDS:
            return SERVICE_WORDS[w]
    return None


def _items_for_service(service, lookup):
    raw = lookup(service) or []
    return [i for i in raw if isinstance(i, str)]


def expand(items, lookup, _seen=None):
    """Flatten a checklist, returning [{'text': str, 'group': str|None}].

    `lookup(service_key)` returns that service's raw item list — passed in so
    this module never touches the database and can be tested on its own.

    Items keep their order. An expanded block carries the name it came from in
    `group`, so the page can fold it; everything else has `group` None. A
    reference that resolves to nothing is left exactly as written rather than
    dropped — better an odd line than a silently shorter checklist.
    """
    _seen = _seen or set()
    out = []
    for item in items:
        if not isinstance(item, str):
            continue
        phrase = reference_phrase(item)
        service = service_for(phrase) if phrase else None
        if not service or service in _seen:
            # Not a reference, or one we are already inside — a template that
            # says "everything in deep" while deep says "everything in move-out"
            # would otherwise recurse until the stack gave out.
            out.append({'text': item, 'group': None})
            continue
        inner = _items_for_service(service, lookup)
        if not inner:
            out.append({'text': item, 'group': None})
            continue
        label = item.strip()
        for sub in expand(inner, lookup, _seen | {service}):
            # A nested block keeps the outermost name: a cleaner folding
            # "Everything in Deep Cleaning" expects the standard items inside it
            # to go with it, not to be a second heading at the same level.
            out.append({'text': sub['text'], 'group': sub['group'] or label})
    return out


def grouped(rows):
    """[(group_or_None, [texts])] in order, for rendering.

    Consecutive items sharing a group become one foldable block; ungrouped items
    each stand alone, so the shape of the original list survives."""
    out = []
    for r in rows:
        if out and out[-1][0] == r['group'] and r['group'] is not None:
            out[-1][1].append(r['text'])
        else:
            out.append((r['group'], [r['text']]))
    return out


def db_lookup(service):
    """The items a service's checklist holds — the owner's, else the built-in.

    Falls back to the work-order defaults because a business that has never
    opened the Checklists page has no template rows at all, and that is exactly
    the business whose cleaners most need the full list spelled out."""
    from models import ChecklistTemplate
    t = ChecklistTemplate.query.filter_by(service_type=service).first()
    if t and t.get_items():
        return t.get_items()
    from blueprints.workorders import DEFAULT_ITEMS
    return DEFAULT_ITEMS.get(service)


def expand_for_booking(items):
    """The flattened checklist for a work order, ready to store."""
    return expand(items, db_lookup)
