#!/usr/bin/env python3
"""Resumable MagicBricks project scraper for missing Delhi NCR components."""
import argparse,json,random,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/raw/magicbricks_delhi_ncr_components'
COMPONENTS={
 'noida':{'id':'6403','name':'Noida','listing':'https://www.magicbricks.com/residential-projects-in-noida--nprid'},
 'gurugram':{'id':'2951','name':'Gurugram','listing':'https://www.magicbricks.com/residential-projects-in-gurgaon--nprid'},
 'ghaziabad':{'id':'6146','name':'Ghaziabad','listing':'https://www.magicbricks.com/residential-projects-in-ghaziabad--nprid'},
 'faridabad':{'id':'2944','name':'Faridabad','listing':'https://www.magicbricks.com/new-projects-Faridabad'},
}
KEEP={'psmid','psid','psmName','devName','pdpUrl','minPrice','maxPrice','minPriceF','maxPriceF','sqFtPrice','sqFtPrMx','totalUnits','prjPossYear','oc','pincode','lmtDName','ctname','visBd','mhDesc'}

def load_seen(path):
 out=set()
 if path.exists():
  for line in path.open(encoding='utf-8'):
   try:
    x=json.loads(line);pid=x.get('psmid') or x.get('psid')
    if pid is not None:out.add(str(pid))
   except:pass
 return out
def fetch(url,attempts=4):
 for attempt in range(attempts):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36','Accept':'application/json,text/plain,*/*','Referer':'https://www.magicbricks.com/'})
   with urllib.request.urlopen(req,timeout=30) as r:
    if r.status==200:return json.loads(r.read().decode('utf-8','ignore'))
  except Exception as e:
   if attempt==attempts-1:print(f'  request failed: {type(e).__name__}',flush=True)
  time.sleep(2**attempt+random.uniform(.5,1.5))
 return None
def scrape(slug,cfg,max_pages):
 OUT.mkdir(parents=True,exist_ok=True);path=OUT/f'{slug}_projects.jsonl';checkpoint=OUT/f'{slug}_checkpoint.json';seen=load_seen(path);start=1
 if checkpoint.exists():
  try:start=int(json.loads(checkpoint.read_text()).get('next_page',1))
  except:pass
 print(f'\n=== {cfg["name"]} ===\nVerified listing: {cfg["listing"]}\nResume page: {start} | Existing IDs: {len(seen):,}',flush=True)
 empty=0;duplicate_pages=0
 with path.open('a',encoding='utf-8') as f:
  for page in range(start,max_pages+1):
   url='https://www.magicbricks.com/mbproject/newProjectCards?'+urllib.parse.urlencode({'pageNo':page,'city':cfg['id'],'possessionCheck':'N'})
   data=fetch(url)
   cards=(data or {}).get('projectsCards') or []
   if not cards:
    empty+=1;print(f'  page {page}: empty ({empty}/3)',flush=True)
    if empty>=3:break
   else:
    empty=0;new=[]
    for card in cards:
     pid=card.get('psmid') or card.get('psid')
     if pid is None or str(pid) in seen:continue
     seen.add(str(pid));row={k:card.get(k) for k in KEEP if k in card};row.update({'psmid':pid,'canonical_city_id':'delhi_ncr','source_component':slug,'source_city_id':cfg['id'],'source_city_name':cfg['name'],'source_listing_url':cfg['listing'],'source_api_url':url,'scraped_at':datetime.now(timezone.utc).isoformat()});new.append(row)
    for row in new:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    f.flush();duplicate_pages=duplicate_pages+1 if not new else 0
    print(f'  page {page}: cards {len(cards)}, new {len(new)}, total {len(seen):,}',flush=True)
    if duplicate_pages>=5 and page>10:
     print('  stopping after 5 repeated pages',flush=True);break
   checkpoint.write_text(json.dumps({'component':slug,'next_page':page+1,'unique_projects':len(seen),'updated_at':datetime.now(timezone.utc).isoformat()},indent=2))
   time.sleep(random.uniform(.6,1.2))
 print(f'Finished {cfg["name"]}: {len(seen):,} unique projects -> {path}',flush=True)
def merge(slugs):
 merged=OUT/'delhi_ncr_missing_components_projects.jsonl';seen=set();count=0
 with merged.open('w',encoding='utf-8') as target:
  for slug in slugs:
   p=OUT/f'{slug}_projects.jsonl'
   if not p.exists():continue
   for line in p.open(encoding='utf-8'):
    x=json.loads(line);pid=str(x.get('psmid') or x.get('psid') or '')
    if not pid or pid in seen:continue
    seen.add(pid);target.write(json.dumps(x,ensure_ascii=False)+'\n');count+=1
 print(f'Merged {count:,} unique projects -> {merged}')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cities',nargs='*',choices=list(COMPONENTS),default=list(COMPONENTS));ap.add_argument('--max-pages',type=int,default=1500);args=ap.parse_args()
 for slug in args.cities:scrape(slug,COMPONENTS[slug],args.max_pages)
 merge(args.cities)
if __name__=='__main__':main()
