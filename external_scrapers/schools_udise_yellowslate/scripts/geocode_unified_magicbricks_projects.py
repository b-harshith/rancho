#!/usr/bin/env python3
import argparse,csv,json,math,os,re,sqlite3,threading,time,urllib.parse,urllib.request
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/'data/output/magicbricks_projects/magicbricks_projects_unified_all_cities.csv'
OUT=ROOT/'data/output/magicbricks_projects/magicbricks_projects_unified_geocoded_v2.csv'
DB=ROOT/'data/output/magicbricks_projects/google_geocode_cache_v2.sqlite'
CITY={
 'delhi_ncr':('Delhi NCR',{'Delhi','Haryana','Uttar Pradesh'}),
 'mumbai':('Mumbai, Maharashtra',{'Maharashtra'}),'hyderabad':('Hyderabad, Telangana',{'Telangana'}),
 'chennai':('Chennai, Tamil Nadu',{'Tamil Nadu'}),'kolkata':('Kolkata, West Bengal',{'West Bengal'}),
 'pune':('Pune, Maharashtra',{'Maharashtra'})}
GENERIC={'route','locality','political','postal_code','neighborhood','administrative_area_level_1','administrative_area_level_2','country'}
STOP={'the','by','project','projects','residency','residencies','apartment','apartments','homes','home','phase','india','private','limited','ltd'}

class RateLimiter:
 def __init__(self,qps):self.interval=1/max(qps,0.1);self.lock=threading.Lock();self.next_at=0.0
 def wait(self):
  with self.lock:
   now=time.monotonic();delay=max(0,self.next_at-now);self.next_at=max(now,self.next_at)+self.interval
  if delay:time.sleep(delay)

LIMITER=None

def num(v):
 try:return float(v)
 except:return None
def tokens(s):return set(re.findall(r'[a-z0-9]+',str(s or '').lower()))-STOP
def similarity(a,b):
 a,b=tokens(a),tokens(b);return len(a&b)/max(1,len(a))
def hav(a,b,c,d):
 r=6371;p1,p2=math.radians(a),math.radians(c);x=math.sin(math.radians(c-a)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(d-b)/2)**2;return 2*r*math.asin(math.sqrt(x))
def components(items):
 out={}
 for c in items:
  for typ in c.get('types',[]):out.setdefault(typ,c.get('long_name',''))
 return out
def assess(row,res):
 geo=res.get('geometry') or {};loc=geo.get('location') or {};lat,lon=num(loc.get('lat')),num(loc.get('lng'));types=set(res.get('types') or []);comp=components(res.get('address_components') or [])
 address=res.get('formatted_address','');country=comp.get('country','');state=comp.get('administrative_area_level_1','');partial=bool(res.get('partial_match'));name_score=similarity(row['name'],address);dev_score=similarity(row.get('developer'),address) if row.get('developer') else 0
 oldlat,oldlon=num(row.get('latitude')),num(row.get('longitude'));distance=hav(oldlat,oldlon,lat,lon) if None not in (oldlat,oldlon,lat,lon) else None
 reasons=[]
 if country not in ('India','IN'):reasons.append('wrong_country')
 allowed=CITY.get(row['city'],('',set()))[1]
 if state and allowed and state not in allowed:reasons.append('wrong_state')
 if types and types<=GENERIC:reasons.append('generic_result_type')
 if distance is not None and distance>3:reasons.append('distance_gt_3km')
 identity_ok=name_score>=0.5 or dev_score>=0.6 or (distance is not None and distance<=0.10 and bool(types- GENERIC))
 if not identity_ok:reasons.append('weak_identity_match')
 if partial and not (distance is not None and distance<=1 and (name_score>=0.5 or dev_score>=0.6)):reasons.append('unsafe_partial_match')
 accepted=not reasons
 confidence='rejected'
 if accepted:
  confidence='high' if distance is not None and distance<=0.5 and not partial and name_score>=0.5 and geo.get('location_type') in ('ROOFTOP','GEOMETRIC_CENTER') else 'medium'
 return {'accepted':accepted,'confidence':confidence,'rejection_reasons':'|'.join(reasons),'distance_from_source_km':round(distance,4) if distance is not None else None,'name_match_score':round(name_score,3),'developer_match_score':round(dev_score,3),'lat':lat,'lon':lon,'place_id':res.get('place_id'),'formatted_address':address,'types':'|'.join(sorted(types)),'location_type':geo.get('location_type'),'partial_match':partial,'locality':comp.get('locality') or comp.get('sublocality_level_1') or comp.get('sublocality'),'pincode':comp.get('postal_code'),'state':state,'country':country}
def request_one(row,key):
 LIMITER.wait()
 city=CITY.get(row['city'],(row['city'],set()))[0];q=', '.join(str(x).strip() for x in (row['name'],row.get('developer'),row.get('locality'),row.get('pincode'),city,'India') if str(x or '').strip());params={'address':q,'components':'country:IN','region':'in','key':key}
 lat,lon=num(row.get('latitude')),num(row.get('longitude'))
 if lat is not None and lon is not None:params['bounds']=f'{lat-.04},{lon-.04}|{lat+.04},{lon+.04}'
 url='https://maps.googleapis.com/maps/api/geocode/json?'+urllib.parse.urlencode(params)
 try:
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as r:data=json.load(r)
  status=data.get('status','UNKNOWN');results=data.get('results') or []
  if not results:return row['project_id'],q,status,{'accepted':False,'confidence':'rejected','rejection_reasons':'no_result'}
  assessed=[assess(row,x) for x in results[:5]];best=sorted(assessed,key=lambda x:(not x['accepted'],-x['name_match_score'],-x['developer_match_score'],x['distance_from_source_km'] if x['distance_from_source_km'] is not None else 99999))[0]
  return row['project_id'],q,status,best
 except Exception as e:return row['project_id'],q,'REQUEST_ERROR',{'accepted':False,'confidence':'rejected','rejection_reasons':type(e).__name__}
def main():
 global LIMITER
 ap=argparse.ArgumentParser();ap.add_argument('--workers',type=int,default=60);ap.add_argument('--qps',type=float,default=45.0);ap.add_argument('--limit',type=int);ap.add_argument('--all',action='store_true');args=ap.parse_args();key=os.environ.get('GOOGLE_MAPS_API_KEY','').strip();LIMITER=RateLimiter(args.qps)
 if not key:raise SystemExit('GOOGLE_MAPS_API_KEY is not set in this terminal')
 rows=list(csv.DictReader(open(INPUT,encoding='utf-8-sig')));DB.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(DB);db.execute('create table if not exists geocodes(project_id text primary key,query text,status text,payload text,updated_at text)');db.commit();done={x[0] for x in db.execute("select project_id from geocodes where status not in ('REQUEST_ERROR','OVER_QUERY_LIMIT','UNKNOWN_ERROR')")};todo=[r for r in rows if r['project_id'] not in done and (args.all or not r.get('latitude') or not r.get('longitude'))]
 if args.limit:todo=todo[:args.limit]
 print(f'V2 safeguarded run | Input {len(rows):,} | Cached {len(done):,} | Requests {len(todo):,} | Rate cap {args.qps:.1f}/sec',flush=True)
 with ThreadPoolExecutor(max_workers=args.workers) as ex:
  for i,f in enumerate(as_completed([ex.submit(request_one,r,key) for r in todo]),1):
   pid,q,status,p=f.result();db.execute('insert or replace into geocodes values(?,?,?,?,datetime("now"))',(pid,q,status,json.dumps(p,separators=(',',':'))))
   if i%100==0:db.commit();print(f'Completed {i:,}/{len(todo):,}',flush=True)
 db.commit();cache={pid:(q,s,json.loads(p)) for pid,q,s,p in db.execute('select project_id,query,status,payload from geocodes')};extra=['google_geocode_query','google_geocode_status','google_match_accepted','google_match_confidence','google_rejection_reasons','google_distance_from_source_km','google_name_match_score','google_developer_match_score','google_latitude','google_longitude','google_place_id','google_formatted_address','google_result_types','google_location_type','google_partial_match','google_locality','google_pincode','google_state','google_country']
 with open(OUT,'w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0])+extra);w.writeheader()
  for r in rows:
   q,s,p=cache.get(r['project_id'],('','NOT_RUN',{}));r.update({'google_geocode_query':q,'google_geocode_status':s,'google_match_accepted':p.get('accepted'),'google_match_confidence':p.get('confidence'),'google_rejection_reasons':p.get('rejection_reasons'),'google_distance_from_source_km':p.get('distance_from_source_km'),'google_name_match_score':p.get('name_match_score'),'google_developer_match_score':p.get('developer_match_score'),'google_latitude':p.get('lat'),'google_longitude':p.get('lon'),'google_place_id':p.get('place_id'),'google_formatted_address':p.get('formatted_address'),'google_result_types':p.get('types'),'google_location_type':p.get('location_type'),'google_partial_match':p.get('partial_match'),'google_locality':p.get('locality'),'google_pincode':p.get('pincode'),'google_state':p.get('state'),'google_country':p.get('country')});w.writerow(r)
 print(OUT)
if __name__=='__main__':main()
