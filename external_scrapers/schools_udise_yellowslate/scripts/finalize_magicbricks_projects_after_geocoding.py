#!/usr/bin/env python3
import csv,json,math,re,hashlib
from collections import defaultdict,Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];DIR=ROOT/'data/output/magicbricks_projects';SRC=DIR/'magicbricks_projects_unified_geocoded_v2.csv'
MASTER=DIR/'magicbricks_projects_final_master.csv';ANALYTIC=DIR/'magicbricks_projects_final_with_units.csv';DUPES=DIR/'magicbricks_projects_duplicate_audit.json';SUMMARY=DIR/'magicbricks_projects_city_summary.json'
def n(v):
 try:return float(v) if str(v).strip() else None
 except:return None
def norm(s):return re.sub(r'[^a-z0-9]+',' ',str(s or '').lower()).strip()
def truth(v):return str(v).lower() in ('true','1','yes')
def hav(a,b,c,d):
 r=6371000;p1,p2=math.radians(a),math.radians(c);x=math.sin(math.radians(c-a)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(d-b)/2)**2;return 2*r*math.asin(math.sqrt(x))
def rank(rows):
 for city in {r['city'] for r in rows}:
  a=[r for r in rows if r['city']==city and n(r.get('price_sqft')) and n(r.get('price_sqft'))>0];a.sort(key=lambda r:(-n(r['price_sqft']),-(n(r.get('max_price')) or 0),-(n(r.get('total_units')) or 0),r['name'].lower()));q4=len(a)//4
  for i,r in enumerate(a):
   r['final_city_rank']=i+1
   if i<q4:r['final_quartile']='Q4'
   else:r['final_quartile']=('Q3','Q2','Q1')[min(2,((i-q4)*3)//max(1,len(a)-q4))]
   r['final_q4_subquartile']='';r['final_q4_segment']=''
  q=a[:q4];base=len(q)//4
  for i,r in enumerate(q):
   if i<base:s,g='Q4-Sub-Q4','Ultra Luxury'
   elif i<base*2:s,g='Q4-Sub-Q3','Super Luxury'
   elif i<base*3:s,g='Q4-Sub-Q2','Elite Luxury'
   else:s,g='Q4-Sub-Q1','Premium Elite'
   r['final_q4_subquartile'],r['final_q4_segment']=s,g
def main():
 if not SRC.exists():raise SystemExit(f'Run safeguarded geocoding first; missing {SRC}')
 rows=list(csv.DictReader(open(SRC,encoding='utf-8-sig')))
 for r in rows:
  accepted=truth(r.get('google_match_accepted'));r['final_latitude']=r.get('google_latitude') if accepted else r.get('latitude');r['final_longitude']=r.get('google_longitude') if accepted else r.get('longitude');r['final_coordinate_source']='google_accepted' if accepted else 'magicbricks_source';r['duplicate_status']='unique';r['duplicate_group_id']='';r['final_city_rank']='';r['final_quartile']='Unranked';r['final_q4_subquartile']='';r['final_q4_segment']=''
 groups=defaultdict(list)
 for r in rows:
  place=r.get('google_place_id') if truth(r.get('google_match_accepted')) else ''
  if place:key=('place',place,norm(r['name']))
  else:key=('fallback',r['city'],norm(r['name']),norm(r.get('locality')))
  groups[key].append(r)
 kept=[];audit=[]
 for key,members in groups.items():
  # Full normalized name is retained in the key, so named phases/towers stay separate.
  if len(members)==1:kept.append(members[0]);continue
  gid='dup_'+hashlib.sha256(str(key).encode()).hexdigest()[:12]
  best=max(members,key=lambda r:(truth(r.get('google_match_accepted')),bool(n(r.get('total_units'))),bool(n(r.get('price_sqft'))),len(r.get('source_url') or '')))
  best['duplicate_status']='representative';best['duplicate_group_id']=gid;best['duplicate_listing_count']=len(members);best['total_units']=max((n(x.get('total_units')) or 0 for x in members),default=0) or ''
  kept.append(best);audit.append({'duplicate_group_id':gid,'key':key,'representative':best['project_id'],'members':[x['project_id'] for x in members],'unit_rule':'max_do_not_sum_duplicate_listings'})
 rank(kept);fields=list(kept[0]);
 for extra in ('duplicate_listing_count',):
  if extra not in fields:fields.append(extra)
 with open(MASTER,'w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(kept,key=lambda r:(r['city'],int(r['final_city_rank']) if str(r['final_city_rank']).isdigit() else 10**9,r['name'])))
 analytical=[r for r in kept if (n(r.get('total_units')) or 0)>0]
 with open(ANALYTIC,'w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(analytical)
 DUPES.write_text(json.dumps(audit,ensure_ascii=False,indent=2))
 summary={}
 for city in sorted({r['city'] for r in kept}):
  a=[r for r in kept if r['city']==city];u=[r for r in a if (n(r.get('total_units')) or 0)>0];summary[city]={'projects':len(a),'projects_with_units':len(u),'reported_units':round(sum(n(r['total_units']) or 0 for r in u)),'google_accepted':sum(r['final_coordinate_source']=='google_accepted' for r in a),'q4_projects':sum(r['final_quartile']=='Q4' for r in a)}
 SUMMARY.write_text(json.dumps(summary,indent=2));print('master',len(kept),MASTER);print('with_units',len(analytical),ANALYTIC);print('duplicate_groups',len(audit),DUPES)
if __name__=='__main__':main()
