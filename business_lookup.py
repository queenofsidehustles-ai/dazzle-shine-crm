"""What we already know about a business, so we do not have to ask for it.

Signup gives a name, an email and a ZIP. Google gives the rest -- phone,
address, website -- for a business that has a listing, and places_finder
already knows how to ask: it does exactly this to find prospects. Pointing it
at the owner's own business is the same request with a different purpose.

This never fails in a way the owner sees. A new company with no listing, a
missing API key, a provider having a bad afternoon: all three come back the
same way, as blanks on a card they were going to be shown anyway. "Here is
what I have" is true whether we found anything or not, where "found you on
Google" would be a promise broken for every business too new to be listed --
which is a good half of the people signing up.
"""
import re


def _norm(name):
    """A business name with the noise taken out, for comparing two of them."""
    out = re.sub(r'[^a-z0-9 ]', ' ', (name or '').lower())
    drop = {'the', 'llc', 'inc', 'co', 'company', 'services', 'service',
            'cleaning', 'cleaners', 'clean', 'maids', 'maid', 'and', 'of'}
    return ' '.join(w for w in out.split() if w and w not in drop)


def _score(wanted, listing):
    """How much a listing looks like the business we were asked about."""
    a, b = _norm(wanted), _norm(listing.get('business_name'))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    aw, bw = set(a.split()), set(b.split())
    if not aw or not bw:
        return 0.0
    overlap = len(aw & bw) / len(aw | bw)
    # A listing that contains the whole of what we were given is a strong
    # match even when it carries extra words: "Sparkle" vs "Sparkle Cleaning
    # of Orlando".
    if a in b or b in a:
        overlap = max(overlap, 0.8)
    return overlap


def find(business_name, zip_code, minimum=0.5):
    """Look one business up. Returns a dict of what was found, possibly empty.

    Keys, when present: phone, address, website, city, state, zip_code.
    Never raises, never returns None, and never puts a guess in: below the
    match threshold we would rather show a blank field than somebody else's
    phone number on this owner's invoices.
    """
    found = {}
    name = (business_name or '').strip()
    zip_code = (zip_code or '').strip()
    if not name or not zip_code:
        return found
    try:
        import places_finder
        ok, listings, _err = places_finder.search_businesses('cleaning', zip_code)
    except Exception:
        return found
    if not ok or not listings:
        return found

    best, best_score = None, 0.0
    for listing in listings:
        s = _score(name, listing)
        if s > best_score:
            best, best_score = listing, s
    if not best or best_score < minimum:
        return found

    if best.get('phone'):
        found['phone'] = best['phone']
    if best.get('website'):
        found['website'] = best['website']
    address = (best.get('address') or '').strip()
    if address:
        found['address'] = address
        parts = [p.strip() for p in address.split(',')]
        # "14 Oak St, Orlando, FL 32801, USA" -- the shape Places returns.
        if len(parts) >= 3:
            found['address'] = parts[0]
            found['city'] = parts[1]
            tail = parts[2].split()
            if tail:
                found['state'] = tail[0][:2].upper()
            if len(tail) > 1 and tail[1][:5].isdigit():
                found['zip_code'] = tail[1][:5]
    return found
