#!/usr/bin/env python3
"""Apply the final ranking with UDISE-backed records ahead of non-UDISE rows."""
import csv, re
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).parent.parent
SOURCE=ROOT/'schools'/'final_schools_29480_ready.csv'
OUTPUT=ROOT/'schools'/'final_schools_29480_ranked.csv'
TIER_ORDER={'Super-Premium':0,'Premium':1,'Affordable':2,'Budget':3}
def number(v):
    try:return float((v or '').replace(',',''))
    except (ValueError,AttributeError):return 0.0
def city_key(v):
    s=re.sub(r'[_\s]+',' ',(v or '').strip().casefold())
    return {'bangalore':'bengaluru'}.get(s,s)
def has_valid_udise(v): return bool(re.fullmatch(r'\d{11}',(v or '').strip()))
def main():
    with SOURCE.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f); fields=reader.fieldnames; rows=list(reader)
    city_premium_enrollment=defaultdict(float)
    for r in rows:
        if r['fee_tier'] in {'Premium','Super-Premium'}:
            city_premium_enrollment[city_key(r['city'])]+=number(r['enrollment_total'])
    rows.sort(key=lambda r:(
        -city_premium_enrollment[city_key(r['city'])],
        city_key(r['city']),
        TIER_ORDER.get(r['fee_tier'],99),
        0 if has_valid_udise(r['udise_code']) else 1,
        -number(r['enrollment_total']),
        r['school_name'].casefold(),
    ))
    for i,r in enumerate(rows,1):r['school_id']=str(i)
    with OUTPUT.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print('rows',len(rows));print('udise_backed',sum(has_valid_udise(r['udise_code']) for r in rows));print(OUTPUT)
if __name__=='__main__':main()
