#!/usr/bin/env python3
"""Remove high-confidence duplicate rows that were reconciled to existing UDISE schools."""
import csv, re
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).parent.parent
SOURCE=ROOT/'schools'/'final_schools_29480_udise_reconciled.csv'
OUTPUT=ROOT/'schools'/'final_schools_deduplicated.csv'
TIER={'Super-Premium':0,'Premium':1,'Affordable':2,'Budget':3}
def num(v):
    try:return float((v or '').replace(',',''))
    except:return 0
def ckey(v):return re.sub(r'[_\s]+',' ',(v or '').strip().casefold()).replace('bangalore','bengaluru')
def main():
    with SOURCE.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f); fields=reader.fieldnames; before=list(reader)
    rows=[r for r in before if r.get('udise_match_confidence')!='high']
    city_enrol=defaultdict(float)
    for r in rows:
        if r['fee_tier'] in {'Premium','Super-Premium'}:city_enrol[ckey(r['city'])]+=num(r['enrollment_total'])
    rows.sort(key=lambda r:(-city_enrol[ckey(r['city'])],ckey(r['city']),TIER.get(r['fee_tier'],99),0 if r.get('udise_code') else 1,-num(r['enrollment_total']),r['school_name'].casefold()))
    for i,r in enumerate(rows,1):r['school_id']=str(i)
    with OUTPUT.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print('before',len(before),'removed_high_confidence_duplicates',len(before)-len(rows),'after',len(rows));print(OUTPUT)
if __name__=='__main__':main()
