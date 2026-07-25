import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/Users/malleswararao/Desktop')
OUT = Path('/Users/malleswararao/Desktop/final new data/premium_school_review')
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'inferred_udise_review_batches').mkdir(exist_ok=True)

FINAL = ROOT / 'school extraction/output/final_master_premium_schools_after_all_city_rematch_city_baseline_fix.csv'
BASE = ROOT / 'final new data/schools/processed/master_schools_all_28947.csv'
EZY = ROOT / 'school extraction/data/client_export/ezy_yellowslate_unified_all_cities.csv'
UDISE = ROOT / 'school extraction/data/client_export/udise_private_unaided_schools.csv'

master = pd.read_csv(FINAL, dtype=str).fillna('')
base = pd.read_csv(BASE, dtype=str).fillna('')
ezy = pd.read_csv(EZY, dtype=str).fillna('')
udise = pd.read_csv(UDISE, dtype=str).fillna('')

for d in (master, ezy):
    for c in ('latitude', 'longitude', 'fee_min', 'fee_max'):
        if c in d:
            d[c + '_num'] = pd.to_numeric(d[c], errors='coerce')

# Restore the authoritative UDISE-derived coordinates and geocode provenance
# that were lost from the previous final export.
base_cols = [
    'udise_code', 'model_score', 'fee_band_calibrated', 'school_level',
    'k12_enrollment', 'grade_2_9_enrollment_est', 'location_type',
    'latitude', 'longitude', 'geocode_status', 'geocode_location_type',
    'geocode_formatted_address', 'geocode_place_id', 'premium_chain',
]
base_cols = [c for c in base_cols if c in base.columns]
out = master.merge(base[base_cols], on='udise_code', how='left', suffixes=('', '_udise'))

# Parse UDISE school category, grade span, management, and address.
ud_rows = []
for raw in udise['summary_json']:
    try:
        ud_rows.append(json.loads(raw))
    except Exception:
        ud_rows.append({})
ud = pd.DataFrame(ud_rows)
keep = ['udise_code', 'schCatDesc', 'classFrm', 'classTo', 'schLocDesc', 'schMgmtDesc', 'address']
ud2 = pd.concat([udise[['udise_code']], ud.reindex(columns=keep[1:])], axis=1)
ud2 = ud2.rename(columns={'address': 'udise_address'})
out = out.merge(ud2, on='udise_code', how='left')

# Exact UDISE-code linkage to the fee-source data; aggregate because a school
# can appear in both sources or have multiple fee records.
ezy2 = ezy[ezy['udise_code'] != ''].copy()
for c in ('fee_min_num', 'fee_max_num'):
    if c not in ezy2:
        ezy2[c] = pd.to_numeric(ezy2[c.replace('_num', '')], errors='coerce')
fee = ezy2.groupby('udise_code', as_index=False).agg(
    fee_source_rows=('school_name', 'size'),
    fee_source_min=('fee_min_num', 'max'),
    fee_source_max=('fee_max_num', 'max'),
    fee_source_categories=('category', lambda s: '|'.join(sorted(set(x for x in s if x)))),
    fee_source_names=('school_name', lambda s: ' | '.join(list(dict.fromkeys(s))[:4])),
    fee_source_urls=('primary_url', lambda s: ' | '.join(list(dict.fromkeys(x for x in s if x))[:4])),
)
out = out.merge(fee, on='udise_code', how='left')

def num(s):
    return pd.to_numeric(s, errors='coerce')

out['evidence_tier'] = np.select(
    [
        out['premium_basis'].eq('actual_fee_above_1L_non_udise_after_rematch'),
        out['premium_basis'].eq('unmatched_fee_gt1L_rematched_to_udise'),
        out['premium_basis'].eq('old_calibrated_gt1L_city_baseline_restore'),
    ],
    ['direct_fee_evidence_non_udise', 'direct_fee_evidence_rematched_to_udise', 'inferred_from_udise'],
    default='unclassified',
)
out['direct_fee_evidence'] = np.where(
    out['evidence_tier'].str.startswith('direct_'), 'yes',
    np.where(out['fee_source_max'].notna(), 'source_match_but_not_used_as_direct_premium_evidence', 'no'),
)
out['fee_evidence_max_observed'] = out['fee_source_max']
out['fee_evidence_category'] = out['fee_source_categories'].fillna('')
out['fee_evidence_source_names'] = out['fee_source_names'].fillna('')
out['fee_evidence_source_urls'] = out['fee_source_urls'].fillna('')

# Coordinate repair: UDISE coordinates from the validated master take priority
# for UDISE rows; non-UDISE rows retain their direct geocoded coordinates.
lat_udise = out['latitude_udise'].fillna('')
lon_udise = out['longitude_udise'].fillna('')
out['final_latitude'] = lat_udise.where(lat_udise.ne(''), out['latitude'])
out['final_longitude'] = lon_udise.where(lon_udise.ne(''), out['longitude'])
out['final_coordinate_source'] = np.where(out['udise_code'].ne(''), 'UDISE_master_geocode', 'fee_source_geocode')
out['final_geocode_type'] = out['geocode_location_type'].where(out['geocode_location_type'].ne(''), '')
out['final_geocode_status'] = out['geocode_status'].where(out['geocode_status'].ne(''), '')
fallback_address = out['address'] if 'address' in out.columns else out.get('udise_address', pd.Series('', index=out.index))
fallback_address = fallback_address.where(fallback_address.ne(''), out.get('udise_address', fallback_address))
out['final_formatted_address'] = out['geocode_formatted_address'].where(out['geocode_formatted_address'].ne(''), fallback_address)

cat = out['schCatDesc'].fillna('').str.lower()
name = out['school_name'].fillna('').str.lower()
out['school_scope_flag'] = np.select(
    [
        cat.str.contains('higher secondary only/jr. college|college', regex=True),
        cat.eq('primary'),
        cat.str.contains('pre-primary', regex=False),
        out['school_level'].fillna('').isin(['Primary Only (1-5)', 'Upper Primary Only (6-8)']),
        out['school_level'].fillna('').isin(['Unknown', 'Other']),
    ],
    ['jr_college_or_higher_secondary_only', 'primary_only', 'pre_primary_only', 'limited_grade_span', 'unknown_grade_span'],
    default='k12_or_mixed',
)
out['name_review_flag'] = np.select(
    [
        name.str.contains(r'\b(anganwadi|balwadi|nursery|play ?school|montessori)\b', regex=True),
        name.str.contains(r'\b(coaching|tutorial|learning centre|learning center)\b', regex=True),
        name.str.contains(r'\b(jr\.? college|degree college|polytechnic|inter college)\b', regex=True),
        name.str.contains(r'\b(public|government|govt|kendriya|navodaya|sainik|army|air force|navy)\b', regex=True),
    ],
    ['early_years_name', 'coaching_or_academy_name', 'college_name', 'public_or_special_name'],
    default='',
)

score = num(out['model_score']).fillna(0)
out['review_risk_score'] = (1 - score).round(4)
out.loc[out['school_scope_flag'].ne('k12_or_mixed'), 'review_risk_score'] += 0.25
out.loc[out['fee_source_max'].notna() & (out['fee_source_max'] < 100000), 'review_risk_score'] += 0.35
out['review_risk_score'] = out['review_risk_score'].round(4)

inferred = out[out['evidence_tier'].eq('inferred_from_udise')].copy()
inferred = inferred.sort_values(['review_risk_score', 'city', 'school_name'], ascending=[False, True, True]).reset_index(drop=True)
inferred['review_batch_id'] = 'UDISE_INFERRED_BATCH_' + (inferred.index // 50 + 1).astype(str).str.zfill(3)
inferred['review_order_in_batch'] = inferred.index % 50 + 1
batch_map = inferred[['udise_code', 'review_batch_id', 'review_order_in_batch']]
out = out.merge(batch_map, on='udise_code', how='left', suffixes=('', '_batch'))
out['validation_status'] = np.where(out['evidence_tier'].eq('inferred_from_udise'), 'pending_individual_validation', 'direct_evidence_present')
out['review_search_query'] = (out['school_name'] + ' ' + out['city'] + ' school fees').str.strip()

# Put the new audit layer first, while retaining every original field.
new_cols = [
    'evidence_tier', 'direct_fee_evidence', 'fee_evidence_max_observed',
    'fee_evidence_category', 'fee_evidence_source_names', 'fee_evidence_source_urls',
    'school_scope_flag', 'name_review_flag', 'validation_status',
    'review_batch_id', 'review_order_in_batch', 'review_risk_score',
    'final_latitude', 'final_longitude', 'final_coordinate_source',
    'final_geocode_type', 'final_geocode_status', 'final_formatted_address',
    'review_search_query',
]
ordered = out[new_cols + [c for c in master.columns if c in out.columns] + [c for c in [
    'udise_code', 'model_score', 'fee_band_calibrated', 'school_level', 'k12_enrollment',
    'grade_2_9_enrollment_est', 'location_type', 'geocode_place_id', 'schCatDesc',
    'classFrm', 'classTo', 'schLocDesc', 'schMgmtDesc', 'udise_address',
] if c in out.columns and c not in master.columns]]
ordered.to_csv(OUT / 'premium_schools_corrected_layered.csv', index=False)

for batch_id, g in inferred.groupby('review_batch_id', sort=True):
    g.to_csv(OUT / 'inferred_udise_review_batches' / f'{batch_id}.csv', index=False)

summary = pd.DataFrame([
    {'metric': 'total_premium_rows', 'value': len(out)},
    {'metric': 'direct_fee_evidence_rows', 'value': int(out['evidence_tier'].str.startswith('direct_').sum())},
    {'metric': 'inferred_from_udise_rows', 'value': int(out['evidence_tier'].eq('inferred_from_udise').sum())},
    {'metric': 'inferred_review_batches_of_50', 'value': int(inferred['review_batch_id'].nunique())},
    {'metric': 'udise_coordinates_restored', 'value': int(((out['udise_code'] != '') & (out['final_latitude'] != '') & (out['latitude'] == '')).sum())},
    {'metric': 'inferred_rows_with_source_fee_match_below_1L', 'value': int(((out['evidence_tier'].eq('inferred_from_udise')) & out['fee_source_max'].notna() & (out['fee_source_max'] < 100000)).sum())},
    {'metric': 'inferred_primary_or_limited_grade_flags', 'value': int(((out['evidence_tier'].eq('inferred_from_udise')) & out['school_scope_flag'].ne('k12_or_mixed')).sum())},
])
summary.to_csv(OUT / 'premium_schools_corrected_layered_summary.csv', index=False)
print(summary.to_string(index=False))
print('output', OUT / 'premium_schools_corrected_layered.csv')
print('batches', inferred['review_batch_id'].nunique())
