
import json
import re
import time
import math
import argparse
import os
import subprocess
import sys
import fcntl
from contextlib import contextmanager
from pathlib import Path
from difflib import SequenceMatcher
from udise_scraper.cdp import CDPBrowser

# Mappings
CITY_STATE_MAP = {
    'delhi_ncr': ('107', 'DELHI'),
    'bangalore': ('129', 'KARNATAKA'),
    'bengaluru': ('129', 'KARNATAKA'),
    'mumbai': ('127', 'MAHARASHTRA'),
    'hyderabad': ('136', 'TELANGANA'),
    'chennai': ('133', 'TAMILNADU'),
    'kolkata': ('119', 'WEST BENGAL'),
    'pune': ('127', 'MAHARASHTRA')
}

NCR_STATES = [('107', 'DELHI'), ('106', 'HARYANA'), ('109', 'UTTAR PRADESH')]

DATA_DIR = Path('/Users/malleswararao/Desktop/school extraction/data/output')
BLR_FILE = Path('/Users/malleswararao/Desktop/BangaloreRancho/web_platform_vercel_exact_latest/src/public/data/school_entities.json')

@contextmanager
def locked_source_file(source_file):
    """Serialize read/modify/write operations shared by browser processes."""
    lock_path = Path('/tmp') / (source_file.name + '.udise-name-scraper.lock')
    with open(lock_path, 'w') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def normalize_name(name):
    if not name:
        return ""
    name = name.lower().strip()
    name = re.sub(r'\bsaint\b', 'st', name)
    name = re.sub(r'\b(shri|sree|shree)\b', 'sri', name)
    name = re.sub(r'\bvidhya\b', 'vidya', name)
    name = re.sub(r'\bcentre\b', 'center', name)
    
    words_to_remove = [
        'school', 'public', 'convent', 'english', 'high', 'primary', 'nursery', 
        'academy', 'international', 'early', 'learning', 'center', 'preschool', 
        'montessori', 'play', 'kindergarten', 'bengaluru', 'bangalore', 'society', 
        'trust', 'foundation', 'association', 'memorial', 'composite', 'residential'
    ]
    pattern = r'\b(' + '|'.join(words_to_remove) + r')\b'
    name = re.sub(pattern, '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

def name_sim(a, b):
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()

def search_name_variants(name):
    """Return conservative UDISE queries from most to least specific."""
    clean = re.sub(r'&(?:amp;)?', ' and ', str(name or ''), flags=re.I)
    clean = re.sub(r'[^A-Za-z0-9\s,()\-/]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip(' ,-/')
    variants = [clean]

    # Remove parenthetical and comma/dash branch or locality suffixes.
    without_parenthetical = re.sub(r'\s*\([^)]*\)\s*', ' ', clean).strip()
    variants.append(without_parenthetical)
    variants.append(re.split(r'\s*[,–—]\s*|\s+-\s+', without_parenthetical, maxsplit=1)[0])

    # Last fallback: retain the distinctive registered-name words.
    generic = {
        'school', 'public', 'international', 'academy', 'high', 'senior',
        'secondary', 'primary', 'nursery', 'preschool', 'the', 'of', 'and',
    }
    core_words = [word for word in re.findall(r'[A-Za-z0-9]+', without_parenthetical)
                  if word.lower() not in generic]
    if len(core_words) >= 2 or (len(core_words) == 1 and len(core_words[0]) >= 6):
        variants.append(' '.join(core_words))

    output = []
    seen = set()
    for variant in variants:
        variant = re.sub(r'\s+', ' ', variant).strip()
        key = variant.lower()
        if len(variant) >= 4 and key not in seen:
            seen.add(key)
            output.append(variant)
    return output[:4]

def search_states(city, pincode):
    """Choose the correct NCR state from PIN where possible."""
    if city != 'delhi_ncr':
        return [CITY_STATE_MAP[city]]
    pin = str(pincode or '').strip()
    if pin.startswith('110'):
        return [('107', 'DELHI')]
    if pin.startswith(('121', '122', '123', '124', '125', '126', '127')):
        return [('106', 'HARYANA')]
    if pin.startswith(('201', '202', '203', '204', '205', '206', '207', '208', '209')):
        return [('109', 'UTTAR PRADESH')]
    return NCR_STATES

def clean_address_words(addr):
    if not addr:
        return set()
    addr = str(addr).lower()
    addr = re.sub(r'[^a-z0-9\s]', ' ', addr)
    words = set(addr.split())
    # Remove common filler words
    stop = {'near', 'opp', 'opposite', 'road', 'street', 'lane', 'main', 'cross', 'behind', 'beside', 'floor', 'building', 'colony', 'layout', 'nagar', 'city', 'bangalore', 'delhi', 'mumbai', 'hyderabad', 'chennai', 'kolkata', 'pune', 'india'}
    return words - stop

def address_matches(cand_addr, cand_pin, udise_addr, udise_pin):
    # Check pincode
    cp = str(cand_pin or '').strip()
    up = str(udise_pin or '').strip()
    if cp and up and cp == up:
        return True, "Pincode Match"
        
    # Check word overlap
    c_words = clean_address_words(cand_addr)
    u_words = clean_address_words(udise_addr)
    if c_words and u_words:
        overlap = c_words.intersection(u_words)
        if len(overlap) >= 1:
            return True, f"Locality/Street overlap ({', '.join(overlap)})"
            
    return False, "No address overlap"

def solve_captcha_via_ocr(browser, ocr_reader):
    # Extract base64 captcha
    img_data = browser.evaluate(
        "(() => { const imgs=[...document.images].filter(i=>i.src.startsWith('data:image/png;base64,')); "
        "return imgs.length ? imgs[imgs.length-1].src : null; })()"
    )
    if not img_data or not img_data.startswith("data:image/png;base64,"):
        return ""
    import base64
    header, base64_data = img_data.split(",", 1)
    img_bytes = base64.b64decode(base64_data)
    result = ocr_reader.readtext(img_bytes)
    text = "".join([res[1] for res in result]).replace(" ", "")
    text = re.sub(r'[^A-Za-z0-9]', '', text)
    return text

def stage_name_search(browser, school_name, state_id):
    """Open and fill the public UDISE form, just like the PIN-code scraper."""
    # Navigating to the same Angular hash can leave the previous form in the DOM
    # briefly. Waiting on that stale form caused retries 2-5 to lose the state.
    browser.navigate("about:blank")
    browser.wait_until("location.href === 'about:blank'", timeout=10)
    browser.navigate("https://kys.udiseplus.gov.in/#/advancesearch")
    browser.wait_until("document.readyState === 'complete'", timeout=30)
    browser.wait_until("document.querySelector('#school') !== null", timeout=30)
    browser.click("#school")
    browser.wait_until("document.querySelector('select.form-select.select') !== null", timeout=20)
    state_selected = browser.evaluate(f"""
        (() => {{
            const select = document.querySelector('select.form-select.select');
            const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
            setter.call(select, {json.dumps(state_id)});
            select.dispatchEvent(new Event('change', {{bubbles:true}}));
            return select.value === {json.dumps(state_id)};
        }})()
    """)
    if not state_selected:
        raise RuntimeError(f"UDISE state dropdown would not retain state {state_id}")
    # This field is Angular-bound; real keyboard events are more reliable than
    # assigning HTMLInputElement.value (which can leave the model empty).
    browser.replace_text("input[type='text']:not([placeholder])", school_name)
    browser.wait_until(
        "(() => { const i=[...document.images].filter(x=>x.src.startsWith('data:image/png;base64,')).at(-1); return i && i.src.length > 100; })()",
        timeout=20,
    )

def submit_name_search(browser, captcha):
    """Submit through Angular's form and parse the result cards rendered by UDISE."""
    browser.set_input_value("input[placeholder='Enter Captcha']", captcha)
    browser.click("button.purpleBtn")
    browser.wait_until(
        "document.body.innerText.includes('Showing Result For') || "
        "document.body.innerText.includes('No Record Found') || "
        "document.body.innerText.includes('No Data Found') || "
        "document.body.innerText.includes('No School Found') || "
        "/Showing\\s+0\\s+Result/i.test(document.body.innerText) || "
        "document.body.innerText.includes('State is required') || "
        "document.body.innerText.toLowerCase().includes('invalid captcha')",
        timeout=10,
    )
    body = browser.evaluate("document.body.innerText") or ""
    no_results = (
        "No Record Found" in body
        or "No Data Found" in body
        or "No School Found" in body
        or re.search(r"Showing\s+0\s+Result", body, re.I)
    )
    if no_results:
        return [], body
    if "Showing Result For" not in body:
        return [], body

    # Ask the page to render up to 100 records before reading its cards.
    browser.evaluate("""
        (() => {
            const s = [...document.querySelectorAll('select')].find(x =>
                [...x.options].some(o => o.value === '100'));
            if (!s) return false;
            s.value = '100';
            s.dispatchEvent(new Event('change', {bubbles:true}));
            return true;
        })()
    """)
    time.sleep(1)
    body = browser.evaluate("document.body.innerText") or ""
    detail_links = browser.evaluate("""
        [...document.querySelectorAll('a')]
          .filter(a => (a.innerText || '').trim() === 'Know More')
          .map(a => a.href)
    """) or []

    cards = []
    chunks = re.split(r'(?=UDISE Code:)', body)
    for chunk in chunks[1:]:
        code = re.search(r'UDISE Code:\s*(\d{11})', chunk)
        name = re.search(r'Edu\. Block\s*:\s*[^\n]*\n([^\n]+)', chunk)
        address = re.search(r'Address:\s*\n?(.+?)\n\s*PIN Code\s*:', chunk, re.S)
        pin = re.search(r'PIN Code\s*:\s*(\d{6})', chunk)
        if not (code and name):
            continue
        link = detail_links[len(cards)] if len(cards) < len(detail_links) else ""
        detail = re.search(r'/schooldetail/([^/]+)/([^/?#]+)', link)
        cards.append({
            "udise_code": code.group(1),
            "school_name": name.group(1).strip(),
            "address": re.sub(r'\s+', ' ', address.group(1)).strip() if address else "",
            "pincode": pin.group(1) if pin else "",
            "school_id": detail.group(1) if detail else "",
            "year_id": detail.group(2) if detail else "11",
        })
    return cards, body

def parse_class_enrollment(enrollment_data):
    totals = enrollment_data.get("schEnrollmentYearDataTotal") or {}
    g2_9 = 0
    total_students = 0
    
    # Sum boys and girls from class 1 to 12
    # Standard labels in report: colcol1BoyTot, colcol1GirlTot, etc.
    levels = [("PRE_PRIMARY", "Pry")]
    levels.extend((str(num), str(num)) for num in range(1, 13))
    
    for label, key in levels:
        boys = int(totals.get(f"col{key}BoyTot") or 0)
        girls = int(totals.get(f"col{key}GirlTot") or 0)
        total = int(totals.get(f"col{key}BoyGirlTot") or boys + girls)
        total_students += total
        if label in ['2', '3', '4', '5', '6', '7', '8', '9']:
            g2_9 += total
            
    return total_students, g2_9

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--workers', type=int,
        default=int(os.environ.get('UDISE_NAME_WORKERS', '1')),
        help='Number of concurrent browser processes (default: 1; validate before increasing)',
    )
    parser.add_argument('--shard-index', type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--shard-count', type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.shard_index is None and args.workers > 1:
        worker_count = max(1, args.workers)
        print(f"Launching {worker_count} concurrent UDISE browser workers...", flush=True)
        processes = []
        for worker_index in range(worker_count):
            command = [
                sys.executable, str(Path(__file__).resolve()), '--workers', '1',
                '--shard-index', str(worker_index), '--shard-count', str(worker_count),
            ]
            processes.append(subprocess.Popen(command, env=os.environ.copy()))
        return_codes = [process.wait() for process in processes]
        failed = [index for index, code in enumerate(return_codes) if code != 0]
        if failed:
            raise SystemExit(f"Browser workers failed: {failed}")
        print("All concurrent browser workers completed.", flush=True)
        return

    import easyocr
    ocr_reader = easyocr.Reader(['en'])
    
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    print("Launching UDISE Browser Session...")
    browser = CDPBrowser(chrome_path, headless=True)
    browser.start()
    
    # Identify unmatched premium schools
    unmatched_schools = []
    
    # 1. Other cities
    for city in CITY_STATE_MAP.keys():
        if city in {'bangalore', 'bengaluru', 'delhi_ncr'}:
            continue
        fpath = DATA_DIR / f'schools_{city}_final.json'
        if fpath.exists():
            with open(fpath) as f:
                schools = json.load(f)
                for s in schools:
                    fee = s.get('fee', 0) or 0
                    if fee >= 100000 and not s.get('udise_code'):
                        unmatched_schools.append({
                            'source_file': fpath,
                            'city': city,
                            'name': s.get('name'),
                            'fee': fee,
                            'predicted_students': s.get('students', 0),
                            'address': s.get('address', ''),
                            'pincode': s.get('pincode', ''),
                            'raw_record': s
                        })
                        
    # 2. Bangalore
    if BLR_FILE.exists():
        with open(BLR_FILE) as f:
            blr = json.load(f)
            for s in blr:
                fee_min = s.get('fee_min')
                fee_max = s.get('fee_max')
                fee = 0
                if fee_min is not None and fee_max is not None:
                    fee = (fee_min + fee_max) / 2
                elif fee_min is not None:
                    fee = fee_min
                elif fee_max is not None:
                    fee = fee_max
                    
                if fee >= 100000 and not s.get('udise_codes'):
                    unmatched_schools.append({
                        'source_file': BLR_FILE,
                        'city': 'bangalore',
                        'name': s.get('name'),
                        'fee': fee,
                        'predicted_students': s.get('students_total', 0) or s.get('students', 0) or 0,
                        'address': s.get('address', ''),
                        'pincode': s.get('pincode', ''),
                        'raw_record': s
                    })
                    
    print(f"Found {len(unmatched_schools)} unmatched premium schools to query.")

    if args.shard_index is not None:
        shard_count = args.shard_count or 1
        unmatched_schools = [
            school for index, school in enumerate(unmatched_schools)
            if index % shard_count == args.shard_index
        ]
        print(
            f"Worker {args.shard_index + 1}/{shard_count}: "
            f"processing {len(unmatched_schools)} schools.",
            flush=True,
        )
    
    matched_count = 0
    
    for idx, s in enumerate(unmatched_schools):
        school_name = s['name']
        city = s['city']
        states = search_states(city, s.get('pincode'))
        queries = search_name_variants(school_name)
        print(f"\n[{idx+1}/{len(unmatched_schools)}] Processing School: '{school_name}' in {city.upper()}")
        
        captcha_solved = False
        udise_results = []

        for state_id, state_name in states:
            for query_name in queries:
                print(f"  Searching {state_name}: {query_name!r}")
                query_completed = False
                for attempt in range(1, 6):
                    try:
                        stage_name_search(browser, query_name, state_id)
                    except Exception as exc:
                        print(f"    Attempt {attempt}: could not stage form ({exc})")
                        continue
                    captcha = solve_captcha_via_ocr(browser, ocr_reader)
                    if len(captcha) != 6:
                        print(f"    Attempt {attempt}: OCR returned {len(captcha)} characters")
                        continue
                    try:
                        results, page_text = submit_name_search(browser, captcha)
                    except Exception as exc:
                        print(f"    Attempt {attempt}: search did not settle ({exc})")
                        continue
                    if "invalid captcha" in page_text.lower():
                        print(f"    Attempt {attempt}: CAPTCHA rejected")
                        continue
                    query_completed = True
                    captcha_solved = True
                    if results:
                        udise_results.extend(results)
                    break
                if udise_results:
                    break
                if not query_completed:
                    print(f"    Could not complete this query after 5 CAPTCHA attempts")
            if udise_results:
                break
                
        if not captcha_solved:
            print(f"  [SKIPPED] Could not complete any UDISE query for '{school_name}'.")
            continue
            
        if not udise_results:
            print(f"  [NO RESULTS] No matches returned on UDISE registry for '{school_name}'.")
            continue
            
        # Try to find a matched school based on name & address criteria
        best_match = None
        best_score = 0
        match_reason = ""
        
        for u in udise_results:
            u_name = u.get("school_name") or u.get("name") or ""
            score = name_sim(school_name, u_name)
            
            if score >= 0.78:
                # Check address overlap
                u_addr = u.get("address") or u.get("location_name") or ""
                u_pin = u.get("pincode") or ""
                is_addr_match, addr_reason = address_matches(s['address'], s['pincode'], u_addr, u_pin)
                
                if is_addr_match:
                    if score > best_score:
                        best_score = score
                        best_match = u
                        match_reason = addr_reason
                        
        if best_match:
            school_id = best_match.get("school_id")
            year_id = best_match.get("year_id") or "11"
            udise_code = best_match.get("udise_code")
            u_name = best_match.get("school_name") or best_match.get("name")
            
            # Fetch Enrollment report
            enroll_url = f"https://kys.udiseplus.gov.in/web-app/api/school-statistics/enrolment-teacher?schoolId={school_id}&yearId={year_id}"
            res_enroll = browser.evaluate(
                f"fetch({json.dumps(enroll_url)}, {{headers: {{'Accept': 'application/json'}}}})"
                ".then(async r => ({statusCode: r.status, text: await r.text()}))"
            )
            
            try:
                enroll_payload = json.loads(res_enroll.get("text") or "{}")
                enroll_data = enroll_payload.get("data") or {}
                tot_students, g2_9_students = parse_class_enrollment(enroll_data)
            except Exception:
                tot_students, g2_9_students = 0, 0
                
            # Print live matched details to terminal
            print(f"  [MATCHED] '{school_name}' -> UDISE: '{u_name}' ({udise_code})")
            print(f"    Match Reason: {match_reason} (Similarity: {best_score:.2f})")
            print(f"    Predicted Enrollment: {s['predicted_students']} | UDISE Enrollment: {tot_students} (Grades 2-9: {g2_9_students})")
            
            # Update source file. Other browser processes may update the same
            # JSON file, so always reload and save while holding its lock.
            source_file = s['source_file']
            with locked_source_file(source_file):
                with open(source_file, 'r') as sf:
                    sf_data = json.load(sf)

                if source_file != BLR_FILE:
                    for item in sf_data:
                        if item.get('name') == school_name:
                            item['udise_code'] = udise_code
                            item['students'] = tot_students
                            item['student_enrollment_grades_2_9'] = g2_9_students
                            item['enrollment_source'] = 'UDISE'
                            break
                else:
                    for item in sf_data:
                        if item.get('name') == school_name:
                            item['udise_codes'] = [udise_code]
                            item['students_total'] = tot_students
                            item['students_grades_2_9'] = g2_9_students
                            item['enrollment_source'] = 'udise'
                            item['merge_status'] = 'auto_matched'
                            break

                with open(source_file, 'w') as sf:
                    json.dump(sf_data, sf, indent=2, ensure_ascii=False)
                
            matched_count += 1
        else:
            print(f"  [UNMATCHED] No UDISE entries met similarity & address matching rules.")
            
    print(f"\nScraping Run Complete. Matched {matched_count} schools by name.")
    browser.close()

if __name__ == "__main__":
    main()
