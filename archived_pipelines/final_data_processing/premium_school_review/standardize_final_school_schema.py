#!/usr/bin/env python3
"""Produce a presentation-ready schema with valid UDISE codes and grade ranges."""
import csv, re
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).parent.parent
SOURCE=ROOT/'schools'/'final_schools_29480_sorted_clean.csv'
OUTPUT=ROOT/'schools'/'final_schools_29480_ready.csv'
LEVELS={
    'Primary Only (1-5)':'Grades 1-5',
    'Primary+Upper Primary (1-8)':'Grades 1-8',
    'Secondary (6-10)':'Grades 6-10',
    'Higher Secondary (6-12)':'Grades 6-12',
    'Higher Secondary (1-12)':'Grades 1-12',
    'Upper Primary Only (6-8)':'Grades 6-8',
    'K-12':'Grades K-12',
    'Unknown':'Unknown',
    'Other':'Other',
}
def main():
    with SOURCE.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f); source_fields=reader.fieldnames; rows=list(reader)
    fields=['school_id']+[('grade_range' if x=='school_level' else x) for x in source_fields]
    levels=Counter(); invalid=0
    for i,r in enumerate(rows,1):
        r['school_id']=str(i)
        if not re.fullmatch(r'\d{11}',r['udise_code'].strip()):
            r['udise_code']='';invalid+=1
        r['grade_range']=LEVELS.get(r.pop('school_level'),'Other')
        levels[r['grade_range']]+=1
    with OUTPUT.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print('rows',len(rows));print('invalid_udise_blank',invalid);print('grade_ranges',dict(levels));print(OUTPUT)
if __name__=='__main__':main()
