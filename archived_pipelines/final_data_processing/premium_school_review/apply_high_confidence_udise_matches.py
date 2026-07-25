#!/usr/bin/env python3
"""Apply only high-confidence UDISE reconciliations and preserve match provenance."""
import csv, re
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).parent.parent
SOURCE=ROOT/'schools'/'final_schools_29480_ranked.csv'
AUDIT=ROOT/'schools'/'non_udise_to_udise_match_audit.csv'
OUTPUT=ROOT/'schools'/'final_schools_29480_udise_reconciled.csv'
TIER={'Super-Premium':0,'Premium':1,'Affordable':2,'Budget':3}
def valid(v):return bool(re.fullmatch(r'\d{11}',(v or '').strip()))
def num(v):
    try:return float((v or '').replace(',',''))
    except:return 0
def ckey(v):return re.sub(r'[_\s]+',' ',(v or '').strip().casefold()).replace('bangalore','bengaluru')
def main():
    with SOURCE.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    with AUDIT.open(encoding='utf-8',newline='') as f:
        matches={r['non_udise_school_id']:r for r in csv.DictReader(f) if r['confidence']=='high'}
    fields+=['udise_match_method','udise_match_confidence']
    applied=0
    for r in rows:
        m=matches.get(r['school_id'])
        r['udise_match_method']='source_udise' if valid(r['udise_code']) else ''
        r['udise_match_confidence']='source' if valid(r['udise_code']) else ''
        if m and not valid(r['udise_code']):
            r['udise_code']=m['matched_udise_code'];r['udise_match_method']=m['match_method'];r['udise_match_confidence']='high';applied+=1
    city_enrol=defaultdict(float)
    for r in rows:
        if r['fee_tier'] in {'Premium','Super-Premium'}:city_enrol[ckey(r['city'])]+=num(r['enrollment_total'])
    rows.sort(key=lambda r:(-city_enrol[ckey(r['city'])],ckey(r['city']),TIER.get(r['fee_tier'],99),0 if valid(r['udise_code']) else 1,-num(r['enrollment_total']),r['school_name'].casefold()))
    for i,r in enumerate(rows,1):r['school_id']=str(i)
    with OUTPUT.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print('applied_high_confidence_matches',applied);print('valid_udise_total',sum(valid(r['udise_code']) for r in rows));print(OUTPUT)
if __name__=='__main__':main()
