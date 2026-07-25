#!/usr/bin/env python3
import csv, re
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).parent.parent
SOURCE=ROOT/'schools'/'final_schools_deduplicated.csv'
DECISIONS=ROOT/'schools'/'non_udise_manual_review_decisions.csv'
OUTPUT=ROOT/'schools'/'final_schools_manual_review_applied.csv'
TIER={'Super-Premium':0,'Premium':1,'Affordable':2,'Budget':3}
def num(v):
    try:return float((v or '').replace(',',''))
    except:return 0
def city(v):return re.sub(r'[_\s]+',' ',(v or '').strip().casefold()).replace('bangalore','bengaluru')
def valid(v):return bool(re.fullmatch(r'\d{11}',(v or '').strip()))
def main():
    with SOURCE.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    with DECISIONS.open(encoding='utf-8',newline='') as f: decisions={r['school_id']:r for r in csv.DictReader(f)}
    kept=[];removed=0
    for r in rows:
        d=decisions.get(r['school_id'])
        if d and d['decision']=='duplicate_existing_school':removed+=1;continue
        if valid(r['udise_code']):r['udise_review_status']='source_udise'
        elif d and d['decision']=='genuinely_not_in_udise':r['udise_review_status']='manually_confirmed_not_in_udise'
        else:r['udise_review_status']='pending_non_udise_review'
        kept.append(r)
    fields=[x for x in fields if x not in {'udise_match_method','udise_match_confidence'}]+['udise_review_status']
    city_enrol=defaultdict(float)
    for r in kept:
        if r['fee_tier'] in {'Premium','Super-Premium'}:city_enrol[city(r['city'])]+=num(r['enrollment_total'])
    kept.sort(key=lambda r:(-city_enrol[city(r['city'])],city(r['city']),TIER.get(r['fee_tier'],99),0 if valid(r['udise_code']) else 1,-num(r['enrollment_total']),r['school_name'].casefold()))
    for i,r in enumerate(kept,1):r['school_id']=str(i)
    with OUTPUT.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r.get(k,'') for k in fields} for r in kept)
    print('input',len(rows),'removed_duplicates',removed,'output',len(kept));print(OUTPUT)
if __name__=='__main__':main()
