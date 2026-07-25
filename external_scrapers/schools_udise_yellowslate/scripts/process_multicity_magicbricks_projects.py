#!/usr/bin/env python3
"""Normalize, clean, dedupe and city-rank MagicBricks projects like Bangalore.

Geocoding is deliberately optional and requires GOOGLE_MAPS_API_KEY in the
environment; this script never embeds or persists the key.
"""
import argparse,csv,hashlib,json,math,os,re
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=Path('/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest')
RAW=BASE/'DATA/raw'; OUT=Path('data/output/magicbricks_projects')
CITIES=['delhi_ncr','mumbai','hyderabad','chennai','kolkata','pune']

def n(v):
 try:return float(v) if v not in ('',None) else None
 except:return None
def norm(s):return re.sub(r'[^a-z0-9]+',' ',str(s or '').lower()).strip()
def stable(city,source_id,name,locality):
 raw='|'.join((city,str(source_id or ''),norm(name),norm(locality)))
 return 'project_'+hashlib.sha256(raw.encode()).hexdigest()[:16]
def classify(name,desc):
 t=norm(name)+' '+norm(desc)
 if any(x in t for x in ('plot','layout','land','sites')):return 'Plot/Land'
 if any(x in t for x in ('villa','row house','rowhouse','bungalow')):return 'Villa/House'
 if any(x in t for x in ('builder floor','independent floor')):return 'Builder Floor'
 return 'Apartment'
def quartiles(rows):
 ranked=sorted([r for r in rows if r['price_sqft'] and r['price_sqft']>0],key=lambda r:(-r['price_sqft'],-(r['max_price'] or 0),-(r['total_units'] or 0),r['name'].lower()))
 unranked=sorted([r for r in rows if not r['price_sqft'] or r['price_sqft']<=0],key=lambda r:r['name'].lower())
 q4=len(ranked)//4
 for i,r in enumerate(ranked):
  if i<q4:r['quartile']='Q4'
  else:
   rem=len(ranked)-q4;b=min(2,((i-q4)*3)//max(rem,1));r['quartile']=('Q3','Q2','Q1')[b]
  r['city_rank']=i+1;r['q4_subquartile']='';r['q4_segment']=''
 q=ranked[:q4];base=len(q)//4
 for i,r in enumerate(q):
  if i<base:sub,seg='Q4-Sub-Q4','Ultra Luxury'
  elif i<base*2:sub,seg='Q4-Sub-Q3','Super Luxury'
  elif i<base*3:sub,seg='Q4-Sub-Q2','Elite Luxury'
  else:sub,seg='Q4-Sub-Q1','Premium Elite'
  r['q4_subquartile'],r['q4_segment']=sub,seg
 for r in unranked:r['quartile']='Unranked';r['q4_subquartile']='';r['q4_segment']='';r['city_rank']=''
 return ranked+unranked
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cities',nargs='*',default=CITIES);ap.add_argument('--geocode',action='store_true');args=ap.parse_args()
 if args.geocode and not os.environ.get('GOOGLE_MAPS_API_KEY'):
  raise SystemExit('GOOGLE_MAPS_API_KEY is required for --geocode')
 OUT.mkdir(parents=True,exist_ok=True);all_rows=[]
 for city in args.cities:
  src=RAW/f'{city}_projects_enriched_and_geocoded.jsonl'
  if not src.exists():print('[missing]',src);continue
  sources=[src]
  if city=='delhi_ncr':
   added=ROOT/'data/raw/magicbricks_delhi_ncr_components/delhi_ncr_missing_components_projects.jsonl'
   if added.exists():sources.append(added)
  best={};quarantine=[]
  for source in sources:
   for line in source.open(encoding='utf-8'):
    if not line.strip():continue
    x=json.loads(line);name=x.get('psmName') or x.get('devName') or '';ptype=x.get('project_type') or classify(name,x.get('mhDesc'))
    if not name or ptype=='Plot/Land':continue
    lat,lon=n(x.get('latitude')),n(x.get('longitude'));sq=n(x.get('sqFtPrice')) or n(x.get('sqFtPrMx'));mn=n(x.get('minPrice')) or n(x.get('minPriceF'));mx=n(x.get('maxPrice')) or n(x.get('maxPriceF'))
    if sq is not None and sq<=0:sq=None
    if sq is not None and not 250<=sq<=200000:quarantine.append({'reason':'price_sqft_outlier_nonzero','record':x});continue
    if mn and mx and mn>mx:mn,mx=mx,mn
    rid=stable(city,x.get('psmid'),name,x.get('lmtDName'));row={'project_id':rid,'source_project_id':str(x.get('psmid') or ''),'name':name,'normalized_name':norm(name),'developer':x.get('devName') or '','city':city,'locality':x.get('lmtDName') or '','pincode':x.get('pincode') or '','latitude':lat,'longitude':lon,'coordinate_status':'available' if lat is not None and lon is not None else 'missing','price_sqft':sq,'price_status':'observed' if sq else 'missing','min_price':mn,'max_price':mx,'total_units':n(x.get('totalUnits')),'possession_year':x.get('prjPossYear') or '','construction_status':x.get('oc') or '','project_type':ptype,'source_url':('https://www.magicbricks.com/'+str(x.get('pdpUrl')).lstrip('/')) if x.get('pdpUrl') else '','scraped_at':x.get('scraped_at') or '','source':'magicbricks'}
    score=sum(v not in (None,'') for v in row.values());old=best.get(rid)
    if old is None or score>old[0]:best[rid]=(score,row)
  rows=quartiles([v[1] for v in best.values()]);all_rows.extend(rows)
  (OUT/f'{city}_projects_cleaned.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
  (OUT/f'{city}_projects_quarantine.json').write_text(json.dumps(quarantine,ensure_ascii=False,indent=2))
  print(city,'clean',len(rows),'quarantine',len(quarantine))
  if args.geocode:print(city,'missing coordinates',sum(r['coordinate_status']=='missing' for r in rows),'(geocoder hook requires supplied key)')
  
 fields=list(all_rows[0]) if all_rows else []
 with open(OUT/'magicbricks_projects_unified_all_cities.csv','w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(sorted(all_rows,key=lambda r:(r['city'],r['city_rank'] if isinstance(r['city_rank'],int) else 10**9,r['name'].lower())))
 print(OUT/'magicbricks_projects_unified_all_cities.csv',len(all_rows))
if __name__=='__main__':main()
