"""Big Fish Finder — pulls PUBLIC business listings (property managers, realtors,
Airbnb hosts, apartment complexes) so the VA gets a ready-to-dial call list.

Uses Google's official Places API (New) — the allowed, above-board way to get
public business info. NOT scraping. Only businesses (which publish their contact
info on purpose); never private consumer data.

House style mirrors payment_service.py: read the key from env, return a
(success, data, error) tuple, never raise.
"""
import requests

# What we actually type into Google for each category the user picks.
CATEGORY_QUERIES = {
    'property_manager': 'property management companies',
    'realtor': 'real estate agents',
    'airbnb': 'short term rental management',
    'apartment': 'apartment complexes',
    'daycare': 'daycares and childcare centers',
    'medical_office': 'doctor offices and medical clinics',
    'general_contractor': 'general contractors and construction companies',
    'office': 'office buildings and business offices',
    'other': 'cleaning service clients',
}

PLACES_URL = 'https://places.googleapis.com/v1/places:searchText'
# Only ask Google for the fields we need — keeps the call in the cheapest tier.
FIELD_MASK = (
    'places.id,places.displayName,places.formattedAddress,'
    'places.nationalPhoneNumber,places.websiteUri,places.rating'
)


def demo_reason():
    """Why sample businesses are showing, in the words the reader needs.

    Two different situations wore one message. On hosted Akye the only one a
    customer can hit is the demo company, and the message told her to set an
    environment variable -- something only the person running the servers can
    do, which on a product she is paying for reads as "this is broken and it
    is your fault". The other case is a single-business install, where setting
    that variable is exactly right and the person reading is the one who can.
    """
    import demo_guard
    if demo_guard.active():
        return 'demo_company'
    return 'no_key'


def own_key():
    """True when the company is searching on its own Google account.

    Then the searches are not ours to ration: they are billed to them, by
    Google, directly. integrations._stored and not get(), because get() falls
    back to the platform key and every company would look like it had brought
    its own."""
    import integrations
    if integrations.platform_managed('google_places_api_key'):
        return False                     # hosted Akye: Akye's key, Akye's allowance
    try:
        return bool((integrations._stored('google_places_api_key') or '').strip())
    except Exception:
        return False


def allowance():
    """Whose allowance this search spends, and whether it is already spent.

    Returns (capped, count_it):

      * demo company -- no call to Google, so nothing to ration or record
      * their own Google key -- their account, their bill, no cap of ours
      * otherwise it comes out of the plan's monthly searches

    One function because the route had the same three cases spread across its
    branches, where no test could reach them.
    """
    if not api_key_present():
        return False, False
    if own_key():
        return False, False
    import entitlements
    return entitlements.at_limit('lead_searches_per_month'), True


def api_key_present():
    import demo_guard
    import integrations
    return not demo_guard.active() and bool(integrations.google_places_api_key())


def search_businesses(category, location, api_key=None):
    """Search public business listings for one category in one place.

    Returns (success: bool, listings: list[dict], error: str).
    Each listing: {place_id, business_name, phone, website, address, city, rating}.
    """
    import demo_guard
    if demo_guard.active():
        return True, demo_listings(category, location), ''
    if not api_key:
        import integrations
        api_key = integrations.google_places_api_key()
    if not api_key:
        return False, [], 'Google Places API key not configured'

    text_query = f"{CATEGORY_QUERIES.get(category, category)} in {location}".strip()
    try:
        resp = requests.post(
            PLACES_URL,
            headers={
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': FIELD_MASK,
            },
            json={'textQuery': text_query, 'maxResultCount': 20},
            timeout=15,
        )
        if resp.status_code != 200:
            detail = ''
            try:
                detail = resp.json().get('error', {}).get('message', '')
            except Exception:
                detail = resp.text[:200]
            return False, [], f'Google Places error ({resp.status_code}): {detail}'

        listings = []
        for p in resp.json().get('places', []):
            listings.append({
                'place_id': p.get('id', ''),
                'business_name': (p.get('displayName') or {}).get('text', 'Unknown'),
                'phone': p.get('nationalPhoneNumber', ''),
                'website': p.get('websiteUri', ''),
                'address': p.get('formattedAddress', ''),
                'city': location,
                'rating': p.get('rating'),
            })
        return True, listings, ''
    except requests.RequestException as e:
        return False, [], f'Network error reaching Google Places: {e}'


_DEMO_NAMES = {
    'property_manager': ['Sunshine Property Management', 'Lakeside Rentals & Management',
                         'Metro Property Partners', 'Palm Grove Property Co.', 'Harbor Point Management'],
    'realtor': ['Sunshine Realty Group', 'Lakeside Real Estate', 'Metro Realty Partners',
                'Palm Grove Homes', 'Harbor Point Realty'],
    'airbnb': ['Sunshine STR Co.', 'Lakeside Vacation Rentals', 'Metro Host Management',
               'Palm Grove Getaways', 'Harbor Point Stays'],
    'apartment': ['Sunshine Apartments', 'Lakeside Apartment Homes', 'Metro Flats',
                  'Palm Grove Residences', 'Harbor Point Apartments'],
    'daycare': ['Sunshine Kids Academy', 'Lakeside Learning Center', 'Little Sprouts Daycare',
                'Palm Grove Preschool', 'Harbor Point Childcare'],
    'medical_office': ['Sunshine Family Medicine', 'Lakeside Dental', 'Metro Medical Clinic',
                       'Palm Grove Pediatrics', 'Harbor Point Health'],
    'general_contractor': ['Sunshine Construction Group', 'Lakeside Builders', 'Metro General Contracting',
                           'Palm Grove Development', 'Harbor Point Construction'],
    'office': ['Sunshine Business Center', 'Lakeside Office Park', 'Metro Corporate Plaza',
               'Palm Grove Offices', 'Harbor Point Suites'],
    'other': ['Sunshine Services', 'Lakeside Co.', 'Metro Group', 'Palm Grove LLC', 'Harbor Point Inc.'],
}


def demo_listings(category, location):
    """Sample results shown when no API key is set yet, so the whole flow is
    visible and clickable. Names match the chosen category. Phone numbers are
    fake (555) placeholders."""
    names = _DEMO_NAMES.get(category, _DEMO_NAMES['other'])
    phones = ['(407) 555-0182', '(407) 555-0413', '(407) 555-0876', '(407) 555-0245', '(407) 555-0631']
    ratings = [4.6, 4.2, 4.8, 3.9, 4.5]
    samples = list(zip(names, phones, ratings))
    out = []
    for i, (name, phone, rating) in enumerate(samples):
        out.append({
            'place_id': f'demo-{category}-{i}',
            'business_name': name,
            'phone': phone,
            'website': '',
            'address': f'{100 + i * 7} Main St, {location}',
            'city': location,
            'rating': rating,
        })
    return out
