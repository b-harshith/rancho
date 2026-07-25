from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
MASTER = ROOT / 'premium_schools_corrected_layered.csv'
EZY = Path('/Users/malleswararao/Desktop/school extraction/data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv')

df = pd.read_csv(MASTER, dtype=str).fillna('')
ezy = pd.read_csv(EZY, dtype=str).fillna('')

# Enrich fee-source coordinates with the original geocoder metadata when a
# Google place ID is available.
ezy_cols = [c for c in ['google_place_id', 'google_location_type', 'google_partial_match', 'geocode_confidence', 'google_result_types', 'google_formatted_address'] if c in ezy.columns]
ezy_meta = ezy[ezy_cols].drop_duplicates('google_place_id') if 'google_place_id' in ezy_cols else pd.DataFrame()
if not ezy_meta.empty:
    df = df.merge(ezy_meta, on='google_place_id', how='left', suffixes=('', '_fee_source'))

df['coord_lat'] = pd.to_numeric(df['final_latitude'], errors='coerce')
df['coord_lon'] = pd.to_numeric(df['final_longitude'], errors='coerce')
df['coord_valid_numeric'] = df['coord_lat'].notna() & df['coord_lon'].notna()
df['coord_in_india'] = df['coord_valid_numeric'] & df['coord_lat'].between(6, 38) & df['coord_lon'].between(68, 98)

bounds = {
    'delhi_ncr': (28.20, 29.00, 76.70, 77.80),
    'hyderabad': (16.90, 17.80, 78.10, 78.80),
    'mumbai': (18.80, 19.60, 72.70, 73.30),
    'bengaluru': (12.70, 13.30, 77.30, 77.90),
    'pune': (18.30, 18.80, 73.60, 74.10),
    'chennai': (12.70, 13.30, 80.00, 80.50),
    'kolkata': (22.30, 23.10, 88.10, 88.60),
}

def in_city(row):
    b = bounds.get(row['city'])
    if not b or not row['coord_valid_numeric']:
        return False
    a, z, c, d = b
    return a <= row['coord_lat'] <= z and c <= row['coord_lon'] <= d

df['coord_in_city_bbox'] = df.apply(in_city, axis=1)
df['coord_rounded_5'] = df['coord_lat'].round(5).astype(str) + '|' + df['coord_lon'].round(5).astype(str)
df['duplicate_coord_count'] = df.groupby('coord_rounded_5')['coord_rounded_5'].transform('size')
df['coordinate_precision_flag'] = np.select(
    [~df['coord_valid_numeric'], df['final_latitude'].str.len() < 7, df['final_longitude'].str.len() < 7],
    ['missing_or_non_numeric', 'low_latitude_precision', 'low_longitude_precision'],
    default='',
)

geo_type = df['final_geocode_type'].replace('', np.nan).fillna(df.get('google_location_type', pd.Series('', index=df.index)))
partial = df.get('google_partial_match', pd.Series('', index=df.index)).fillna('')
confidence = df.get('geocode_confidence', pd.Series('', index=df.index)).fillna('')
df['coordinate_geocoder_type'] = geo_type.fillna('')
df['coordinate_partial_match'] = partial
df['coordinate_confidence'] = confidence

df['coordinate_review_reasons'] = ''
def add_reason(mask, reason):
    df.loc[mask, 'coordinate_review_reasons'] = df.loc[mask, 'coordinate_review_reasons'].where(
        df.loc[mask, 'coordinate_review_reasons'].eq(''),
        df.loc[mask, 'coordinate_review_reasons'] + '; '
    ) + reason

add_reason(~df['coord_valid_numeric'], 'missing_or_non_numeric')
add_reason(df['coord_valid_numeric'] & ~df['coord_in_india'], 'outside_india_bounds')
add_reason(df['coord_in_india'] & ~df['coord_in_city_bbox'], 'outside_city_bbox')
add_reason(df['duplicate_coord_count'] >= 3, 'duplicate_coordinate_cluster_3_plus')
add_reason(df['coordinate_geocoder_type'].isin(['APPROXIMATE', 'RANGE_INTERPOLATED']), 'non_rooftop_geocode')
add_reason(df['coordinate_geocoder_type'].eq('GEOMETRIC_CENTER'), 'geometric_center_not_rooftop')
add_reason(df['coordinate_partial_match'].astype(str).str.lower().eq('true'), 'partial_google_match')
add_reason(df['coordinate_confidence'].astype(str).str.lower().eq('low'), 'low_geocode_confidence')

df['coordinate_quality_status'] = np.select(
    [
        ~df['coord_valid_numeric'] | ~df['coord_in_india'],
        df['coord_in_india'] & ~df['coord_in_city_bbox'],
        df['coordinate_geocoder_type'].isin(['APPROXIMATE', 'RANGE_INTERPOLATED']) | df['coordinate_partial_match'].astype(str).str.lower().eq('true') | df['coordinate_confidence'].astype(str).str.lower().eq('low'),
        df['coordinate_geocoder_type'].eq('GEOMETRIC_CENTER') | (df['duplicate_coord_count'] >= 3),
    ],
    ['invalid_coordinate', 'outside_expected_city_area', 'low_confidence_review', 'usable_but_review'],
    default='good_candidate',
)

df['coordinate_action'] = np.select(
    [
        df['coordinate_quality_status'].eq('invalid_coordinate'),
        df['coordinate_quality_status'].eq('outside_expected_city_area'),
        df['coordinate_quality_status'].isin(['low_confidence_review', 'usable_but_review']),
    ],
    ['replace_coordinate', 'verify_city_and_replace_if_needed', 'manual_coordinate_review'],
    default='retain_pending_spot_check',
)

summary = df.groupby(['final_coordinate_source', 'coordinate_geocoder_type', 'coordinate_quality_status'], dropna=False).size().reset_index(name='rows')
summary.to_csv(ROOT / 'coordinate_quality_summary.csv', index=False)

queue = df[df['coordinate_quality_status'].ne('good_candidate')].copy()
queue = queue.sort_values(['coordinate_quality_status', 'city', 'school_name'])
queue.to_csv(ROOT / 'coordinate_review_queue.csv', index=False)

keep = [
    'udise_code', 'school_name', 'city', 'area', 'address', 'pincode',
    'evidence_tier', 'validation_status', 'final_latitude', 'final_longitude',
    'final_coordinate_source', 'coordinate_geocoder_type', 'coordinate_confidence',
    'coordinate_partial_match', 'duplicate_coord_count', 'coord_in_city_bbox',
    'coordinate_quality_status', 'coordinate_action', 'coordinate_review_reasons',
    'google_formatted_address', 'source_url', 'google_place_id', 'review_batch_id',
]
keep = [c for c in keep if c in df.columns]
df[keep].to_csv(ROOT / 'premium_schools_coordinates_quality_checked.csv', index=False)

print('TOTAL', len(df))
print('STATUS')
print(df['coordinate_quality_status'].value_counts().to_string())
print('SOURCE')
print(df['final_coordinate_source'].value_counts().to_string())
print('GEO TYPE')
print(df['coordinate_geocoder_type'].replace('', 'MISSING_TYPE').value_counts().to_string())
print('REVIEW QUEUE', len(queue))
