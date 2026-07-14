"""Big Fish Finder — pulls PUBLIC business listings (property managers, realtors,
Airbnb hosts, apartment complexes) so the VA gets a ready-to-dial call list.

Uses Google's official Places API (New) — the allowed, above-board way to get
public business info. NOT scraping. Only businesses (which publish their contact
info on purpose); never private consumer data.

House style mirrors payment_service.py: read the key from env, return a
(success, data, error) tuple, never raise.
"""
import os
import requests

# What we actually type into Google for each category the user picks.
CATEGORY_QUERIES = {
    'property_manager': 'property management companies',
    'realtor': 'real estate agents',
    'airbnb': 'short term rental management',
    'apartment': 'apartment complexes',
    'daycare': 'daycares and childcare centers',
    'medical_office': 'doctor offices and medical clinics',
    'office': 'office buildings and business offices',
    'other': 'cleaning service clients',
}

PLACES_URL = 'https://places.googleapis.com/v1/places:searchText'
# Only ask Google for the fields we need — keeps the call in the cheapest tier.
FIELD_MASK = (
    'places.id,places.displayName,places.formattedAddress,'
    'places.nationalPhoneNumber,places.websiteUri,places.rating'
)


def api_key_present():
    return bool(os.environ.get('GOOGLE_PLACES_API_KEY'))


def search_businesses(category, location, api_key=None):
    """Search public business listings for one category in one place.

    Returns (success: bool, listings: list[dict], error: str).
    Each listing: {place_id, business_name, phone, website, address, city, rating}.
    """
    api_key = api_key or os.environ.get('GOOGLE_PLACES_API_KEY')
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


def demo_listings(category, location):
    """Sample results shown when no API key is set yet, so the whole flow is
    visible and clickable tonight. Phone numbers are fake (555) placeholders."""
    label = CATEGORY_QUERIES.get(category, category).title()
    samples = [
        ('Sunshine ' + label.split()[0] + ' Group', '(407) 555-0182', 4.6),
        ('Lakeside Rentals & Management', '(407) 555-0413', 4.2),
        ('Metro Realty Partners', '(407) 555-0876', 4.8),
        ('Palm Grove Property Co.', '(407) 555-0245', 3.9),
        ('Harbor Point Management', '(407) 555-0631', 4.5),
    ]
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
