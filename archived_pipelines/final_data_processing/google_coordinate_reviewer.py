#!/usr/bin/env python3
"""Resumable Google Maps coordinate reviewer for the premium-school master.

Dry run:
  python3 google_coordinate_reviewer.py

Live Google validation:
  GOOGLE_MAPS_API_KEY=... python3 google_coordinate_reviewer.py --live

The script never overwrites the source master. It writes a review table and a
JSON cache so a stopped live run can resume without repeating completed calls.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
INPUT = ROOT / 'premium_schools_coordinates_quality_checked.csv'
OUT = ROOT / 'google_coordinate_review_results.csv'
CACHE = ROOT / 'google_coordinate_review_cache.json'


CITY_BOUNDS = {
    'delhi_ncr': (28.20, 29.00, 76.70, 77.80),
    'hyderabad': (16.90, 17.80, 78.10, 78.80),
    'mumbai': (18.80, 19.60, 72.70, 73.30),
    'bengaluru': (12.70, 13.30, 77.30, 77.90),
    'pune': (18.30, 18.80, 73.60, 74.10),
    'chennai': (12.70, 13.30, 80.00, 80.50),
    'kolkata': (22.30, 23.10, 88.10, 88.60),
}


def norm(value):
    value = str(value or '').lower()
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def tokens(value):
    stop = {'school', 'the', 'of', 'and', 'for', 'in', 'at', 'sr', 'sec', 'secondary'}
    return {x for x in norm(value).split() if x not in stop and len(x) > 1}


def jaccard(a, b):
    aa, bb = tokens(a), tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def haversine_m(a_lat, a_lon, b_lat, b_lon):
    r = 6371008.8
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def in_city(row, lat, lon):
    bounds = CITY_BOUNDS.get(row.get('city', ''))
    if not bounds:
        return False
    a, z, c, d = bounds
    return a <= lat <= z and c <= lon <= d


def request_json(url, method='GET', body=None, headers=None, max_retries=5, backoff_factor=2):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    if body is not None:
        req.data = json.dumps(body).encode('utf-8')
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                sleep_time = backoff_factor ** attempt
                print(f"HTTP Error {e.code} for {url}. Retrying in {sleep_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(sleep_time)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < max_retries - 1:
                sleep_time = backoff_factor ** attempt
                print(f"Network error {e} for {url}. Retrying in {sleep_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(sleep_time)
                continue
            raise



def cache_key(prefix, value):
    return prefix + ':' + hashlib.sha1(value.encode('utf-8')).hexdigest()


def reverse_geocode(row, key):
    lat, lon = row['coord_lat'], row['coord_lon']
    query = f'{lat},{lon}'
    url = 'https://maps.googleapis.com/maps/api/geocode/json?' + urllib.parse.urlencode({
        'latlng': query, 'key': key, 'language': 'en', 'region': 'in',
    })
    data = request_json(url)
    results = data.get('results') or []
    best = results[0] if results else {}
    components = {t: c.get('long_name', '') for c in best.get('address_components', []) for t in c.get('types', [])}
    return {
        'status': data.get('status', ''),
        'formatted_address': best.get('formatted_address', ''),
        'place_id': best.get('place_id', ''),
        'location_type': (best.get('geometry') or {}).get('location_type', ''),
        'city': components.get('locality') or components.get('administrative_area_level_2', ''),
        'state': components.get('administrative_area_level_1', ''),
        'pincode': components.get('postal_code', ''),
        'types': best.get('types', []),
    }


def places_search(row, key):
    query = f"{row.get('school_name', '')}, {row.get('city', '')}, India"
    body = {
        'textQuery': query,
        'locationBias': {
            'circle': {
                'center': {'latitude': row['coord_lat'], 'longitude': row['coord_lon']},
                'radius': 5000.0,
            }
        },
        'languageCode': 'en',
        'regionCode': 'IN',
    }
    headers = {
        'Content-Type': 'application/json',
        'X-Goog-Api-Key': key,
        'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.location,places.types,places.businessStatus,places.websiteUri,places.googleMapsUri',
    }
    data = request_json('https://places.googleapis.com/v1/places:searchText', method='POST', body=body, headers=headers)
    candidates = []
    for place in data.get('places') or []:
        loc = place.get('location') or {}
        if 'latitude' not in loc or 'longitude' not in loc:
            continue
        plat, plon = float(loc['latitude']), float(loc['longitude'])
        candidates.append({
            'place_id': place.get('id', ''),
            'name': (place.get('displayName') or {}).get('text', ''),
            'address': place.get('formattedAddress', ''),
            'latitude': plat,
            'longitude': plon,
            'distance_m': round(haversine_m(row['coord_lat'], row['coord_lon'], plat, plon), 2),
            'name_similarity': round(jaccard(row.get('school_name', ''), (place.get('displayName') or {}).get('text', '')), 4),
            'types': place.get('types', []),
            'business_status': place.get('businessStatus', ''),
            'website': place.get('websiteUri', ''),
            'google_maps_uri': place.get('googleMapsUri', ''),
        })
    candidates.sort(key=lambda x: (-x['name_similarity'], x['distance_m']))
    return candidates[:5]


def streetview_metadata(row, key):
    url = 'https://maps.googleapis.com/maps/api/streetview/metadata?' + urllib.parse.urlencode({
        'location': f"{row['coord_lat']},{row['coord_lon']}", 'key': key,
    })
    data = request_json(url)
    loc = data.get('location') or {}
    distance = ''
    if 'lat' in loc and 'lng' in loc:
        distance = round(haversine_m(row['coord_lat'], row['coord_lon'], float(loc['lat']), float(loc['lng'])), 2)
    return {'status': data.get('status', ''), 'date': data.get('date', ''), 'distance_m': distance}


def check_city_match(expected_city, reverse_city, reverse_state):
    exp = norm(expected_city)
    rev = norm(reverse_city)
    state = norm(reverse_state)
    
    if exp in rev or rev in exp:
        return True
        
    if exp == 'bengaluru' and 'bangalore' in rev:
        return True
        
    if exp == 'delhi ncr':
        ncr_keywords = {
            'delhi', 'new delhi', 'noida', 'greater noida', 'ghaziabad', 'gurugram', 'gurgaon', 
            'faridabad', 'hapur', 'dadri', 'modinagar', 'pilkhuwa', 'bahadurgarh', 'sonipat', 
            'kundli', 'sohna', 'dharuhera', 'bhiwadi'
        }
        if any(k in rev for k in ncr_keywords) or state in {'delhi', 'haryana', 'uttar pradesh'}:
            return True
            
    if exp == 'hyderabad':
        hyd_keywords = {
            'hyderabad', 'secunderabad', 'miyapur', 'hayathnagar', 'balapur', 'bandlaguda', 
            'serilingampalle', 'vanasthalipuram', 'ramachandrapuram', 'gundlapochampally', 
            'kondapur', 'gachibowli', 'manikonda', 'narsingi', 'peerzadiguda', 'boduppal', 
            'jallapally', 'medchal'
        }
        if any(k in rev for k in hyd_keywords):
            return True
            
    if exp == 'mumbai':
        mum_keywords = {
            'mumbai', 'navi mumbai', 'thane', 'kalyan', 'mira bhayandar', 'vasai virar', 
            'panvel', 'bhiwandi', 'ambernath', 'badlapur', 'kharghar', 'ulwe', 'uran', 
            'dombivli', 'ulhasnagar'
        }
        if any(k in rev for k in mum_keywords):
            return True
            
    if exp == 'bengaluru':
        blr_keywords = {
            'bengaluru', 'bangalore', 'hebbagodi', 'andapura', 'doddaballapura', 
            'madanayakanahalli', 'manduru', 'kanakapura', 'bidadi', 'kodigehalli', 
            'avalahalli', 'nelamangala', 'yelahanka', 'krishnarajapuram', 'kengeri'
        }
        if any(k in rev for k in blr_keywords):
            return True
            
    if exp == 'pune':
        pune_keywords = {
            'pune', 'pimpri chinchwad', 'baramati', 'marunji', 'talegaon dabhade', 
            'kirkee', 'chakan', 'daund', 'khubavali', 'awasari khurd', 'hinjawadi', 
            'hadapsar', 'wagholi', 'loni kalbhor'
        }
        if any(k in rev for k in pune_keywords):
            return True
            
    if exp == 'chennai':
        chennai_keywords = {
            'chennai', 'avadi', 'tambaram', 'mambakkam', 'padur', 'kattankulathur', 
            'varadharajapuram', 'sriperumbudur', 'thoraipakkam', 'thiruporur', 
            'pattabiram', 'guduvancheri', 'poonamallee', 'sholinganallur', 'kelambakkam'
        }
        if any(k in rev for k in chennai_keywords):
            return True
            
    if exp == 'kolkata':
        kol_keywords = {
            'kolkata', 'howrah', 'bidhannagar', 'salt lake', 'rajarhat', 'dum dum', 
            'north dumdum', 'south dumdum', 'presidency division', 'uttarpara', 
            'kalyani', 'barasat', 'madhyamgram'
        }
        if any(k in rev for k in kol_keywords):
            return True
            
    return False


def decide(row, reverse, candidates, streetview):
    reasons = []
    lat, lon = row['coord_lat'], row['coord_lon']
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return 'reject_invalid', 0.0, 'invalid_lat_lon'
    if not in_city(row, lat, lon):
        reasons.append('outside_expected_city_bbox')
    best = candidates[0] if candidates else {}
    
    # Fix falsy float bug:
    distance = best.get('distance_m')
    if distance is None or distance == '':
        distance = 999999.0
    else:
        distance = float(distance)
        
    similarity = float(best.get('name_similarity') or 0)
    place_types = set(best.get('types') or [])
    school_type = bool(place_types & {'school', 'secondary_school', 'primary_school', 'university'})
    
    reverse_city = reverse.get('city', '')
    reverse_state = reverse.get('state', '')
    city_match = check_city_match(row.get('city', ''), reverse_city, reverse_state)
    
    input_pincode = str(row.get('pincode') or '').strip()
    rev_pincode = str(reverse.get('pincode') or '').strip()
    if input_pincode:
        pincode_match = (input_pincode == rev_pincode)
    else:
        pincode_match = True  # don't penalize missing input pincode
        
    if not city_match:
        reasons.append('reverse_geocode_city_mismatch')
    if not pincode_match and input_pincode:
        reasons.append('reverse_geocode_pincode_mismatch')
    if not candidates:
        reasons.append('no_places_candidate')
    elif distance > 500:
        reasons.append('best_place_over_500m_away')
    elif distance > 150:
        reasons.append('best_place_over_150m_away')
    if candidates and similarity < 0.35:
        reasons.append('weak_name_match')
    if candidates and not school_type:
        reasons.append('best_place_not_school_type')
    if reverse.get('location_type') in {'APPROXIMATE', 'RANGE_INTERPOLATED', 'GEOMETRIC_CENTER'}:
        reasons.append('reverse_geocode_not_rooftop')
    if streetview.get('status') not in {'OK', 'ZERO_RESULTS'}:
        reasons.append('streetview_metadata_error')
    if not candidates:
        return 'needs_research', 0.15, ';'.join(reasons)
    if distance <= 150 and similarity >= 0.60 and school_type and city_match and pincode_match:
        return 'auto_pass', 0.95, ';'.join(reasons)
    if distance <= 300 and similarity >= 0.45 and school_type and city_match:
        return 'manual_review', 0.70, ';'.join(reasons)
    return 'replace_or_research', 0.30, ';'.join(reasons)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Call Google Maps APIs; default is deterministic dry run.')
    parser.add_argument('--limit', type=int, default=0, help='Process only the first N rows.')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    with INPUT.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]
    for row in rows:
        row['coord_lat'] = float(row['final_latitude']) if row.get('final_latitude') else float('nan')
        row['coord_lon'] = float(row['final_longitude']) if row.get('final_longitude') else float('nan')
    cache = json.loads(CACHE.read_text(encoding='utf-8')) if CACHE.exists() else {}
    key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    output = []
    try:
        for idx, row in enumerate(rows, 1):
            key_id = row.get('udise_code') or (row.get('school_name', '') + '|' + row.get('city', ''))
            base = {
                'listing_id': key_id,
                'udise_code': row.get('udise_code', ''),
                'school_name': row.get('school_name', ''),
                'city': row.get('city', ''),
                'pincode': row.get('pincode', ''),
                'latitude': row.get('final_latitude', ''),
                'longitude': row.get('final_longitude', ''),
                'coordinate_source': row.get('final_coordinate_source', ''),
                'existing_quality_status': row.get('coordinate_quality_status', ''),
            }
            if not math.isfinite(row['coord_lat']) or not math.isfinite(row['coord_lon']):
                base.update({'review_decision': 'reject_invalid', 'review_confidence': 1.0, 'review_reasons': 'missing_or_non_numeric'})
                output.append(base)
                continue
            if args.live and not key:
                raise SystemExit('GOOGLE_MAPS_API_KEY is required with --live')
            if args.live:
                ck = cache_key('reverse', key_id + '|' + base['latitude'] + '|' + base['longitude'])
                reverse = cache.get(ck)
                if reverse is None:
                    reverse = reverse_geocode(row, key); cache[ck] = reverse
                ck = cache_key('places', key_id + '|' + row.get('school_name', '') + '|' + row.get('city', ''))
                places = cache.get(ck)
                if places is None:
                    places = places_search(row, key); cache[ck] = places
                ck = cache_key('streetview', base['latitude'] + '|' + base['longitude'])
                streetview = cache.get(ck)
                if streetview is None:
                    streetview = streetview_metadata(row, key); cache[ck] = streetview
                if idx % 25 == 0:
                    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
                    print(f'processed {idx}/{len(rows)}')
            else:
                reverse = {'status': 'DRY_RUN', 'location_type': row.get('coordinate_geocoder_type', ''), 'city': row.get('city', ''), 'pincode': row.get('pincode', '')}
                places = []
                streetview = {'status': 'NOT_RUN'}
            if args.live:
                decision, confidence, reasons = decide(row, reverse, places, streetview)
            else:
                status = row.get('coordinate_quality_status', '')
                decision = {'good_candidate': 'manual_review', 'usable_but_review': 'manual_review', 'low_confidence_review': 'manual_review', 'outside_expected_city_area': 'replace_or_research', 'invalid_coordinate': 'reject_invalid'}.get(status, 'manual_review')
                confidence = {'good_candidate': 0.70, 'usable_but_review': 0.45, 'low_confidence_review': 0.25}.get(status, 0.10)
                reasons = row.get('coordinate_review_reasons', '')
            base.update({
                'review_decision': decision,
                'review_confidence': confidence,
                'review_reasons': reasons,
                'reverse_geocode_json': json.dumps(reverse, ensure_ascii=False),
                'places_candidates_json': json.dumps(places, ensure_ascii=False),
                'streetview_metadata_json': json.dumps(streetview, ensure_ascii=False),
                'recommended_latitude': (places[0].get('latitude', '') if args.live and places else ''),
                'recommended_longitude': (places[0].get('longitude', '') if args.live and places else ''),
                'recommended_place_id': (places[0].get('place_id', '') if args.live and places else ''),
                'recommended_address': (places[0].get('address', '') if args.live and places else ''),
                'distance_to_recommended_m': (places[0].get('distance_m', '') if args.live and places else ''),
            })
            output.append(base)
    finally:
        if args.live:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    fields = sorted({k for row in output for k in row})
    with OUT.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(output)
    print('rows', len(output))
    print('output', OUT)
    print('live', args.live)


if __name__ == '__main__':
    main()
