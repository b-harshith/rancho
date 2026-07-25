#!/usr/bin/env python3
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
RAW = Path('/Users/malleswararao/Desktop/final new data/schools/raw/udise_private_unaided_with_enrollment.csv')
FEE_DATA = Path('/Users/malleswararao/Desktop/final new data/schools/processed/schools_geocoded_unified_with_campuses.csv')
DB = ROOT / 'data/runtime/udise_data.sqlite3'
SHP = Path('/tmp/india_pincodes/india_pincodes.shp')
OUT = ROOT / 'output/udise_pincode_india_map.html'
CSV_OUT = ROOT / 'output/udise_pincode_summary.csv'


def grade_2_9(body):
    try:
        total = body['data']['schEnrollmentYearDataTotal']
        return sum(int(total.get(f'col{i}BoyGirlTot') or 0) for i in range(2, 10))
    except (TypeError, KeyError, ValueError):
        return 0


def main():
    schools = []
    with RAW.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            pin = ''.join(c for c in row['pincode'] if c.isdigit()).zfill(6)
            if len(pin) == 6:
                row['pincode'] = pin
                schools.append(row)

    # Year ID 11 is the latest captured class-wise report card available for
    # essentially all schools in this scrape (year 13 only has summary totals).
    detailed = {}
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    q = """
      SELECT school_id, body_json FROM network_responses
      WHERE url LIKE '%getSocialData?flag=1%yearId=11%'
        AND body_json IS NOT NULL
    """
    for school_id, body in con.execute(q):
        try:
            value = grade_2_9(json.loads(body))
            if value > 0:
                detailed[str(school_id)] = value
        except json.JSONDecodeError:
            pass
    con.close()

    # Roll fee-bearing entities up to unique campuses. A campus can appear on
    # several source rows, so counting raw rows would overstate the comparison.
    fee_candidates = {}
    with FEE_DATA.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            try:
                fee = max(float(row.get('fee') or 0), float(row.get('fee_min') or 0),
                          float(row.get('fee_max') or 0))
            except ValueError:
                fee = 0
            try:
                highest = float(row.get('highest_class') or 0)
            except ValueError:
                highest = 0
            pin = ''.join(c for c in (row.get('pincode') or '') if c.isdigit())
            if len(pin) != 6:
                continue
            campus = row.get('campus_id') or row.get('udise_code') or row.get('school_name')
            try:
                enrollment = float(row.get('campus_students_grades_2_9') or
                                   row.get('student_enrollment_grades_2_9') or 0)
            except ValueError:
                enrollment = 0
            item = fee_candidates.setdefault(campus, {'pincode': pin, 'enrollment': 0,
                                                       'fee': 0, 'highest': 0})
            item['fee'] = max(item['fee'], fee)
            item['highest'] = max(item['highest'], highest)
            item['enrollment'] = max(item['enrollment'], enrollment)
    fee_campuses = {k: v for k, v in fee_candidates.items()
                    if v['fee'] > 0 and v['highest'] != 2}

    agg = defaultdict(lambda: {'school_count': 0, 'grade_2_9': 0, 'schools_with_detail': 0,
                               'fee_school_count': 0, 'fee_grade_2_9': 0,
                               'state': '', 'districts': set()})
    for row in schools:
        a = agg[row['pincode']]
        a['school_count'] += 1
        a['state'] = row['state_name'].strip()
        a['districts'].add(row['district_name'].strip())
        val = detailed.get(str(row['school_id']), 0)
        a['grade_2_9'] += val
        a['schools_with_detail'] += int(val > 0)

    for campus in fee_campuses.values():
        if campus['pincode'] in agg:
            agg[campus['pincode']]['fee_school_count'] += 1
            agg[campus['pincode']]['fee_grade_2_9'] += round(campus['enrollment'])

    gdf = gpd.read_file(SHP)
    gdf['pincode'] = gdf['pincode'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(6)
    gdf = gdf[gdf['pincode'].isin(agg)].copy()
    # Multiple post-office polygons can share one PIN; dissolve into one feature.
    gdf = gdf[['pincode', 'geometry']].dissolve(by='pincode', as_index=False)
    gdf['geometry'] = gdf.geometry.simplify(0.003, preserve_topology=True)
    for key in ['school_count', 'grade_2_9', 'schools_with_detail', 'fee_school_count',
                'fee_grade_2_9', 'state']:
        gdf[key] = gdf['pincode'].map(lambda p: agg[p][key])
    gdf['districts'] = gdf['pincode'].map(lambda p: ', '.join(sorted(agg[p]['districts'])))

    matched = set(gdf['pincode'])
    with CSV_OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['pincode', 'state', 'districts', 'udise_school_count',
                    'udise_grade_2_9_enrollment', 'schools_with_grade_detail',
                    'fee_school_count', 'fee_school_grade_2_9_enrollment', 'polygon_matched'])
        for pin in sorted(agg):
            a = agg[pin]
            w.writerow([pin, a['state'], ', '.join(sorted(a['districts'])), a['school_count'],
                        a['grade_2_9'], a['schools_with_detail'], a['fee_school_count'],
                        a['fee_grade_2_9'], pin in matched])

    geo = json.loads(gdf.to_json(drop_id=True))
    payload = json.dumps(geo, separators=(',', ':'))
    stats = {
        'schools': len(schools), 'pins': len(agg), 'mapped': len(matched),
        'enrollment': sum(a['grade_2_9'] for a in agg.values()),
        'detail_schools': sum(a['schools_with_detail'] for a in agg.values()),
        'fee_schools': sum(a['fee_school_count'] for a in agg.values()),
        'fee_enrollment': sum(a['fee_grade_2_9'] for a in agg.values()),
    }
    html = TEMPLATE.replace('__GEOJSON__', payload).replace('__STATS__', json.dumps(stats))
    OUT.write_text(html, encoding='utf-8')
    print(json.dumps(stats, indent=2))
    print(f'HTML: {OUT}\nCSV: {CSV_OUT}')


TEMPLATE = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UDISE Schools by India PIN Code</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box} body{margin:0;font-family:Inter,system-ui,sans-serif;background:#07111f;color:#e9f1ff}
#map{height:100vh;width:100%}.panel{position:absolute;z-index:1000;top:18px;left:18px;width:340px;max-width:calc(100% - 36px);background:rgba(7,17,31,.93);border:1px solid #29405c;border-radius:16px;padding:18px;box-shadow:0 14px 40px #0008;backdrop-filter:blur(10px)}
h1{font-size:19px;margin:0 0 5px}.sub{font-size:12px;color:#9fb1c8;line-height:1.4}.stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0}.stat{background:#101f33;border-radius:10px;padding:10px}.stat b{display:block;font-size:18px}.stat span{font-size:10px;color:#9fb1c8;text-transform:uppercase;letter-spacing:.06em}
label{display:block;font-size:11px;color:#9fb1c8;margin:10px 0 5px}select,input{width:100%;background:#0d1b2d;color:#fff;border:1px solid #36506f;border-radius:8px;padding:8px}.legend{margin-top:12px;font-size:11px;color:#9fb1c8}.bar{height:8px;border-radius:5px;background:linear-gradient(90deg,#fff3b0,#f8961e,#d00000);margin:5px 0}.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#101f33;color:#fff}.pop b{font-size:16px}.pop div{margin-top:5px}.note{font-size:10px;color:#8094ad;margin-top:12px}
@media(max-width:600px){.panel{top:8px;left:8px;padding:12px;width:290px}.stats{display:none}}
</style></head><body><div id="map"></div>
<div class="panel"><h1>UDISE Schools by PIN Code</h1><div class="sub">Private unaided recognised schools · India-wide polygon overlay</div>
<div class="stats"><div class="stat"><b id="schools"></b><span>UDISE schools</span></div><div class="stat"><b id="feeSchools"></b><span>Schools with fees</span></div><div class="stat"><b id="enroll"></b><span>UDISE Gr. 2–9</span></div><div class="stat"><b id="feeEnroll"></b><span>Fee-school Gr. 2–9</span></div></div>
<label>Colour polygons by</label><select id="metric"><option value="school_count">UDISE school count</option><option value="fee_school_count">Schools with fee data</option><option value="grade_2_9">UDISE Grade 2–9 enrollment</option><option value="fee_grade_2_9">Fee-school Grade 2–9 enrollment</option></select>
<label>Find PIN code</label><input id="search" maxlength="6" placeholder="Type a 6-digit PIN and press Enter">
<div class="legend"><span id="legendTitle">School count</span><div class="bar"></div><div style="display:flex;justify-content:space-between"><span>Lower</span><span>Higher</span></div></div>
<div class="note">Fee schools are unique campuses with a positive fee; schools whose highest offered grade is exactly 2 are excluded. UDISE Grade 2–9 totals use class-wise report-card data (year ID 11) for schools in the year-13 raw extract. PIN polygons are approximate DataMeet/data.gov.in boundaries.</div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const data=__GEOJSON__, stats=__STATS__; const fmt=n=>Number(n||0).toLocaleString('en-IN');
schools.textContent=fmt(stats.schools);feeSchools.textContent=fmt(stats.fee_schools);enroll.textContent=fmt(stats.enrollment);feeEnroll.textContent=fmt(stats.fee_enrollment);
const map=L.map('map',{zoomControl:false}).setView([22.8,79.2],5);L.control.zoom({position:'bottomright'}).addTo(map);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{attribution:'&copy; OpenStreetMap &copy; CARTO',maxZoom:19}).addTo(map);
let metric='school_count', layer; const values=k=>data.features.map(f=>+f.properties[k]||0); const ramp=['#fff3b0','#f9c74f','#f8961e','#f3722c','#d00000'];
function color(v,max){if(!v)return '#24364d';let x=Math.log1p(v)/Math.log1p(max);return ramp[Math.min(4,Math.floor(x*5))]}
function draw(){if(layer)map.removeLayer(layer);let max=Math.max(...values(metric));layer=L.geoJSON(data,{style:f=>({color:'#07111f',weight:.55,fillColor:color(+f.properties[metric],max),fillOpacity:.78}),onEachFeature:(f,l)=>{let p=f.properties;l.bindPopup(`<div class="pop"><b>PIN ${p.pincode}</b><div>${p.state} · ${p.districts}</div><div><strong>${fmt(p.school_count)}</strong> UDISE schools · <strong>${fmt(p.grade_2_9)}</strong> Gr. 2–9 students</div><div><strong>${fmt(p.fee_school_count)}</strong> schools with fees · <strong>${fmt(p.fee_grade_2_9)}</strong> Gr. 2–9 students</div><div>${fmt(p.schools_with_detail)} UDISE schools with class detail</div></div>`);l.on({mouseover:e=>e.target.setStyle({weight:2,color:'#fff'}),mouseout:e=>layer.resetStyle(e.target)});}}).addTo(map)}
const labels={school_count:'UDISE school count',fee_school_count:'Schools with fee data',grade_2_9:'UDISE Grade 2–9 enrollment',fee_grade_2_9:'Fee-school Grade 2–9 enrollment'};
draw(); metric.onchange=e=>{metric=e.target.value;legendTitle.textContent=labels[metric];draw()};
search.onkeydown=e=>{if(e.key==='Enter'){let pin=e.target.value.trim(),hit;layer.eachLayer(l=>{if(l.feature.properties.pincode===pin)hit=l});if(hit){map.fitBounds(hit.getBounds(),{maxZoom:12});hit.openPopup()}else alert('No mapped UDISE polygon found for PIN '+pin)}};
</script></body></html>'''

if __name__ == '__main__':
    main()
