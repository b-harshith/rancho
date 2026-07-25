#!/usr/bin/env python3
"""Run the existing Practo browser scraper sequentially for unscripted cities."""
import argparse, os, subprocess, sys, yaml
from pathlib import Path

ROOT = Path('/Users/malleswararao/Desktop/BangaloreRancho')
SCRAPER = ROOT/'city_rerun_bundle/scripts/source/hospitals/practo_hospitals_scraper.py'
OUTDIR = ROOT/'city_rerun_bundle/data'
DEFAULT = ['mumbai','hyderabad','chennai','kolkata','pune']
REGISTRY = ROOT/'web_platform_vercel_exact_latest/config/cities.yaml'
PLAYWRIGHT_PYTHONS = [
    Path('/Users/malleswararao/Desktop/Rancho Labs/K12-schools-data-extractor/.venv/bin/python'),
    Path(sys.executable),
]

def playwright_python():
    for executable in PLAYWRIGHT_PYTHONS:
        if executable.exists() and subprocess.run(
            [str(executable),'-c','from playwright.async_api import async_playwright'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        ).returncode == 0:
            return str(executable)
    raise SystemExit('No Python environment with Playwright is available.')

def configured_remaining():
    doc=yaml.safe_load(REGISTRY.read_text())
    wanted=set(DEFAULT); ordered=[]
    for city in doc.get('cities',[]):
        cid=city.get('canonical_city_id'); practo=((city.get('source_mappings') or {}).get('practo') or {})
        slug=practo.get('city_slug') or practo.get('city_query')
        if cid in wanted and slug:
            ordered.append((cid,slug,practo.get('verified_url') or ''))
    return ordered

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cities',nargs='*',default=None)
    ap.add_argument('--force',action='store_true')
    args=ap.parse_args(); OUTDIR.mkdir(parents=True,exist_ok=True)
    scraper_python=playwright_python()
    print(f'Using Playwright Python: {scraper_python}',flush=True)
    failures=[]
    configured=configured_remaining()
    if args.cities:
        requested=set(args.cities);configured=[x for x in configured if x[0] in requested or x[1] in requested]
    for city,practo_slug,verified_url in configured:
        out=OUTDIR/f'practo_hospitals_{city}.jsonl'
        if out.exists() and out.stat().st_size and not args.force:
            print(f'[skip] {city}: {out} already exists',flush=True);continue
        print(f'\n=== PRACTO {city.upper()} ===\nRegistry URL: {verified_url}',flush=True)
        env={**os.environ,'CITY_SLUG':practo_slug}
        result=subprocess.run([scraper_python,str(SCRAPER)],cwd=ROOT/'city_rerun_bundle',env=env)
        if result.returncode:
            failures.append(city);print(f'[failed] {city}; continuing',flush=True)
        else: print(f'[done] {city}',flush=True)
    if failures:
        print('Failed cities:',', '.join(failures));raise SystemExit(1)
if __name__=='__main__':main()
