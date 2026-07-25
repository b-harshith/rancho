#!/usr/bin/env python3
"""
School Data Unified Pipeline Orchestrator (Pure Python Edition)
Consolidates scraping, fee calculations, geocoding, and alternate portal enrichments.
Outputs final summaries exclusively to the data/ directory.
Usage:
  python3 run_pipeline.py --city bangalore --step all
"""

import os
import sys
import json
import csv
import re
import time
import random
import argparse
import urllib.parse
from statistics import mean, median
import requests
from bs4 import BeautifulSoup
import sqlite3
import math


try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

# ─────────────────────────────────────────────────────────────────────────────
#  SQLite Database Utilities
# ─────────────────────────────────────────────────────────────────────────────

def get_db_conn(city_slug):
    db_path = f"data/school_scraping_{city_slug}.db"
    os.makedirs("data", exist_ok=True)
    return sqlite3.connect(db_path)

def init_db(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schools_discovery (
            url TEXT PRIMARY KEY,
            name TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS school_details (
            school_id TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            city TEXT,
            raw_details_json TEXT,
            raw_fees_json TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

def evolve_schema(conn, details_payload):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(school_details)")
    existing_cols = {row[1].lower() for row in cursor.fetchall()}
    
    for key, value in details_payload.items():
        col_name = key.lower()
        if col_name in existing_cols:
            continue
            
        sql_type = None
        if isinstance(value, str):
            sql_type = "TEXT"
        elif isinstance(value, bool):
            sql_type = "INTEGER"
        elif isinstance(value, int):
            sql_type = "INTEGER"
        elif isinstance(value, float):
            sql_type = "REAL"
            
        if sql_type:
            safe_col_name = re.sub(r'[^a-z0-9_]', '_', col_name)
            try:
                cursor.execute(f"ALTER TABLE school_details ADD COLUMN {safe_col_name} {sql_type}")
                existing_cols.add(col_name)
            except Exception as e:
                # Alter table could fail if column already exists (race or casing)
                pass
    conn.commit()

# ─────────────────────────────────────────────────────────────────────────────
#  Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def get_city_slugs(city_name):
    clean_name = city_name.strip().replace('-', ' ').title()
    slug_name = city_name.strip().lower().replace(' ', '-')
    return slug_name, clean_name

def clean_float(val):
    if val is None or val == "NA":
        return None
    try:
        return float(val)
    except ValueError:
        return None

def clean_school_name_query(name):
    name = name.lower()
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    # Remove words that interfere with search queries
    stop_words = {'school', 'public', 'private', 'the', 'of', 'and', 'for', 'in', 'high', 'primary', 'secondary'}
    words = [w for w in name.split() if w not in stop_words]
    return " ".join(words)

# ─────────────────────────────────────────────────────────────────────────────
#  Ezyschooling API Scraper Helpers
# ─────────────────────────────────────────────────────────────────────────────

def normalize_name_es(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    stop_words = {'school', 'public', 'private', 'the', 'of', 'and', 'for', 'in', 'high', 'primary', 'secondary', 'composite', 'co', 'education', 'junior', 'college', 'international', 'academy'}
    words = [w for w in name.split() if w not in stop_words]
    return " ".join(words)

def parse_ezyschooling_fee_val(school):
    avg_fees_obj = school.get("avg_fees", {})
    if not avg_fees_obj:
        return "NA"
    session_data = avg_fees_obj.get("2026-2027") or avg_fees_obj.get("2025-2026")
    if session_data:
        class_wise = session_data.get("class_wise", {})
        if class_wise:
            class_yearly_fees = []
            for class_id, class_info in class_wise.items():
                fees_numbers = class_info.get("fees_numbers")
                tenure = class_info.get("tenure", "monthly")
                if fees_numbers:
                    try:
                        val = float(fees_numbers)
                        if val <= 0:
                            continue
                        if tenure.lower() == "monthly":
                            val *= 12
                        elif tenure.lower() == "quarterly":
                            val *= 4
                        class_yearly_fees.append(val)
                    except ValueError:
                        pass
            if class_yearly_fees:
                return round(max(class_yearly_fees), 2)
        range_info = session_data.get("range", {})
        if range_info:
            lowest = range_info.get("lowest_fee")
            highest = range_info.get("highest_fee")
            tenure = range_info.get("tenure", "monthly")
            if lowest is not None and highest is not None:
                try:
                    l_val = float(lowest)
                    h_val = float(highest)
                    if l_val > 0 and h_val > 0:
                        max_val = max(l_val, h_val)
                        if tenure.lower() == "monthly":
                            max_val *= 12
                        elif tenure.lower() == "quarterly":
                            max_val *= 4
                        return round(max_val, 2)
                except ValueError:
                    pass
    avg_fee = avg_fees_obj.get("avg_fee")
    if avg_fee:
        try:
            val = float(avg_fee)
            if val > 0:
                tenure = "monthly"
                if session_data and session_data.get("range"):
                    tenure = session_data["range"].get("tenure", "monthly")
                if tenure.lower() == "monthly":
                    val *= 12
                elif tenure.lower() == "quarterly":
                    val *= 4
                return round(val, 2)
        except ValueError:
            pass
    return "NA"

def parse_classes_es(offered_classes):
    if not offered_classes or offered_classes.strip() == "":
        return "NA", "NA"
    parts = offered_classes.split(' - ')
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    elif len(parts) == 1:
        return parts[0].strip(), parts[0].strip()
    return "NA", "NA"

def normalize_board_es(board_list):
    if not board_list:
        return "Unknown"
    boards = []
    for b in board_list:
        name = b.get("name", "").strip()
        if "CBSE" in name.upper():
            boards.append("CBSE")
        elif "ICSE" in name.upper() or "CISCE" in name.upper():
            boards.append("ICSE")
        elif "IB" in name.upper():
            boards.append("IB")
        elif "IGCSE" in name.upper():
            boards.append("IGCSE")
        elif "STATE" in name.upper():
            boards.append("State board")
        elif "NO BOARD" in name.upper():
            boards.append("No Board")
        else:
            boards.append(name)
    boards = sorted(list(set(boards)))
    return ", ".join(boards) if boards else "Unknown"

# ─────────────────────────────────────────────────────────────────────────────
#  UniApply Scraper Parsing & Merging Helpers
# ─────────────────────────────────────────────────────────────────────────────

def word_jaccard(s1, s2):
    if not s1 or not s2:
        return 0.0
    w1 = set(s1.split())
    w2 = set(s2.split())
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)

def haversine_distance(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        r = 6371000 # Earth's radius in meters
        return c * r
    except Exception:
        return float('inf')

def parse_uniapply_fees(class_fees_map):
    if not class_fees_map:
        return "NA"
    costs = []
    for cls, fee_info in class_fees_map.items():
        tc = fee_info.get("total_cost")
        if tc is not None:
            try:
                val = float(tc)
                if val > 0:
                    costs.append(val)
            except ValueError:
                pass
    if costs:
        return round(max(costs), 2)
    return "NA"

def parse_uniapply_ratio(details):
    val = details.get("student_faculty_ratio") or details.get("student_teacher_ratio")
    if val:
        val_str = str(val).strip()
        if ":" in val_str:
            return val_str
        digits = re.findall(r'\d+', val_str)
        if digits:
            return f"{digits[0]}:1"
    return "NA"

def parse_uniapply_teacher_count(details):
    keys = ["total_faculty", "teacher_count", "total_teachers", "faculty_count"]
    for k in keys:
        val = details.get(k)
        if val:
            digits = re.findall(r'\d+', str(val))
            if digits:
                return int(digits[-1])
    return "NA"

def parse_uniapply_classes(details, class_fees_map):
    classes_offered = details.get("classes_offered", "")
    if classes_offered and isinstance(classes_offered, str) and "-" in classes_offered:
        parts = classes_offered.split('-')
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
            
    if class_fees_map:
        keys = list(class_fees_map.keys())
        def get_class_rank(name):
            n = name.lower().strip()
            if "play" in n or "nursery" in n or "pre-nursery" in n:
                return 0
            if "lkg" in n or "l.k.g" in n or "lower kg" in n or "lower-kg" in n:
                return 1
            if "ukg" in n or "u.k.g" in n or "upper kg" in n or "upper-kg" in n:
                return 2
            if "kg" in n or "kindergarten" in n:
                return 1.5
            if "1" in n or "first" in n or "one" in n:
                return 3
            if "2" in n or "second" in n or "two" in n:
                return 4
            if "3" in n or "third" in n or "three" in n:
                return 5
            if "4" in n or "fourth" in n or "four" in n:
                return 6
            if "5" in n or "fifth" in n or "five" in n:
                return 7
            if "6" in n or "sixth" in n or "six" in n:
                return 8
            if "7" in n or "seventh" in n or "seven" in n:
                return 9
            if "8" in n or "eighth" in n or "eight" in n:
                return 10
            if "9" in n or "ninth" in n or "nine" in n:
                return 11
            if "10" in n or "tenth" in n or "ten" in n:
                return 12
            if "11" in n or "eleventh" in n or "eleven" in n:
                return 13
            if "12" in n or "twelfth" in n or "twelve" in n:
                return 14
            return 99
            
        sorted_keys = sorted(keys, key=get_class_rank)
        if sorted_keys:
            return sorted_keys[0], sorted_keys[-1]
            
    return "NA", "NA"

# ─────────────────────────────────────────────────────────────────────────────
#  Search engine query utilities
# ─────────────────────────────────────────────────────────────────────────────

def search_yahoo_ezyschooling(query, city_clean):
    if curl_requests is None:
        print("  [Warning] curl_cffi not available. Skipping alternate search.")
        return []
    
    url = f"https://search.yahoo.com/search?p={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for attempt in range(3):
        try:
            r = curl_requests.get(url, headers=headers, impersonate="chrome", timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    # Resolve redirects
                    if 'r.search.yahoo.com' in href:
                        match = re.search(r'RU=([^/]+)', href)
                        if match:
                            href = urllib.parse.unquote(match.group(1))
                    
                    if 'ezyschooling.com/school/' in href:
                        # Clean link
                        target = href.split('&')[0].split('?')[0]
                        links.append(target)
                
                # Deduplicate links preserving order
                seen = set()
                return [x for x in links if not (x in seen or seen.add(x))]
        except Exception as e:
            print(f"    Yahoo attempt {attempt+1} failed: {e}")
        time.sleep(random.uniform(2, 4))
    return []

def scrape_ezyschooling_fees(url):
    if curl_requests is None:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for attempt in range(3):
        try:
            r = curl_requests.get(url, headers=headers, impersonate="chrome", timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                page_text = soup.get_text()
                
                fees = []
                # Match class-wise fees patterns (e.g. Nursery - Rs. 4,500 Monthly)
                pattern = re.compile(r'(?:Rs\.|INR|₹)\s*([0-9,]+)\s*(?:Monthly|Per Month|Quarterly|Annually|Yearly)', re.IGNORECASE)
                matches = pattern.findall(page_text)
                for m in matches:
                    val = float(m.replace(',', ''))
                    # Standard multiplier check based on tenure keyword nearby
                    # We default to monthly if not specified, capped to annual range
                    idx = page_text.find(m)
                    snippet = page_text[max(0, idx-40):min(len(page_text), idx+40)].lower()
                    if "monthly" in snippet or "per month" in snippet:
                        val *= 12
                    elif "quarterly" in snippet:
                        val *= 4
                    if val > 0:
                        fees.append(val)
                
                if fees:
                    return {
                        "url": url,
                        "average_fee": round(max(fees), 2),
                        "fee_count": len(fees),
                        "valid_fees": fees
                    }
        except Exception as e:
            print(f"    Scrape attempt {attempt+1} failed: {e}")
        time.sleep(random.uniform(2, 4))
    return None

def search_yahoo_edustoke(query):
    if curl_requests is None:
        return []
    url = f"https://search.yahoo.com/search?p={urllib.parse.quote(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for attempt in range(3):
        try:
            r = curl_requests.get(url, headers=headers, impersonate="chrome", timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if 'r.search.yahoo.com' in href:
                        match = re.search(r'RU=([^/]+)', href)
                        if match:
                            href = urllib.parse.unquote(match.group(1))
                    
                    if 'edustoke.com/' in href and '/preschool/' not in href:
                        target = href.split('&')[0].split('?')[0]
                        links.append(target)
                seen = set()
                return [x for x in links if not (x in seen or seen.add(x))]
        except Exception as e:
            print(f"    Yahoo attempt {attempt+1} failed: {e}")
        time.sleep(random.uniform(2, 4))
    return []

def scrape_edustoke_fees(url):
    if curl_requests is None:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for attempt in range(3):
        try:
            r = curl_requests.get(url, headers=headers, impersonate="chrome", timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                page_text = re.sub(r'\s+', ' ', soup.get_text(separator=' '))
                
                annual_fee = None
                annual_match = re.search(r'(?:Annual|Yearly)\s*Fee\s*₹\s*([0-9,]+)', page_text, re.IGNORECASE)
                if annual_match:
                    annual_fee = annual_match.group(1)
                else:
                    annum_match = re.search(r'₹\s*([0-9,]+)\s*/?\s*Annum', page_text, re.IGNORECASE)
                    if annum_match:
                        annual_fee = annum_match.group(1)
                        
                others_fee = None
                others_match = re.search(r'Others\s*Fee\s*₹\s*([0-9,]+)', page_text, re.IGNORECASE)
                if others_match:
                    others_fee = others_match.group(1)
                    
                annual_num = float(annual_fee.replace(',', '')) if annual_fee else None
                others_num = float(others_fee.replace(',', '')) if others_fee else 0.0
                
                if annual_num is not None:
                    total_fee = annual_num + others_num
                    if total_fee > 0:
                        return {
                            "url": url,
                            "annual_fee": annual_num,
                            "others_fee": others_num,
                            "total_fee": total_fee
                        }
                return {"url": url, "total_fee": None}
        except Exception as e:
            print(f"    Scrape attempt {attempt+1} failed: {e}")
        time.sleep(random.uniform(2, 4))
    return None

# ─────────────────────────────────────────────────────────────────────────────
#  UniApply Scraper Helpers & Steps
# ─────────────────────────────────────────────────────────────────────────────

def parse_fees_html_python(html):
    result = {
        "total_cost": None,
        "monthly_cost": None,
        "period": "for first year",
        "components": [],
        "notes": []
    }
    
    if not html:
        return result
        
    # 1. Extract total cost
    total_cost_match = re.search(r'class="text-big"[^>]*>(?:<span[^>]*></span>)?([0-9,]+)', html)
    if total_cost_match:
        result["total_cost"] = int(total_cost_match.group(1).replace(',', ''))
        
    # Match period (e.g. for first year)
    period_match = re.search(r'<small class="cb-dark">([^<]+)</small>', html)
    if period_match:
        result["period"] = period_match.group(1).strip()
        
    # 2. Extract monthly cost
    monthly_cost_match = re.search(r'Monthly Cost</small>\s*<div[^>]*>\s*<div[^>]*>(?:<span[^>]*></span>)?([0-9,]+)', html, re.IGNORECASE)
    if monthly_cost_match:
        result["monthly_cost"] = int(monthly_cost_match.group(1).replace(',', ''))
        
    # 3. Decode HTML entities
    decoded = (html
               .replace('&lt;', '<')
               .replace('&gt;', '>')
               .replace('&quot;', '"')
               .replace('&#39;', "'")
               .replace('&amp;', '&'))
               
    # 4. Extract components from table rows
    row_regex = re.compile(r'<tr>\s*<td>\s*<strong>([^<]+)</strong>[\s\S]*?<td>\s*(?:&#x20B9;|₹|INR)?\s*([0-9,]+)\s*</td>\s*<td>\s*([^<\n\r]+)\s*</td>\s*</tr>', re.IGNORECASE)
    for row_match in row_regex.finditer(decoded):
        fee_type = row_match.group(1).strip()
        amount = int(row_match.group(2).replace(',', ''))
        frequency = row_match.group(3).strip()
        result["components"].append({
            "fee_type": fee_type,
            "amount": amount,
            "frequency": frequency,
            "total": amount
        })
        
    # Fallback for popover calculator components if table parse is empty
    if not result["components"]:
        comp_regex = re.compile(r'<td>([^<]+)</td>\s*<td[^>]*>(?:<span[^>]*></span>)?₹([0-9,]+)\s*X\s*(\d+)', re.IGNORECASE)
        for comp_match in comp_regex.finditer(decoded):
            fee_type = comp_match.group(1).strip()
            amount = int(comp_match.group(2).replace(',', ''))
            frequency = int(comp_match.group(3))
            result["components"].append({
                "fee_type": fee_type,
                "amount": amount,
                "frequency": f"{frequency} times",
                "total": amount * frequency
            })
            
    # 5. Extract Notes/Instructions
    notes_match = re.search(r'class="[^"]*fee-notes[^"]*"[\s\S]*?<ul[^>]*>([\s\S]*?)</ul>', decoded)
    if notes_match:
        li_matches = re.findall(r'<li>([\s\S]*?)</li>', notes_match.group(1))
        for li_text in li_matches:
            note_text = re.sub(r'<[^>]*>', '', li_text)
            note_text = re.sub(r'\s+', ' ', note_text).strip()
            if note_text:
                result["notes"].append(note_text)
                
    return result

def extract_uniapply_school_details(html_content, school_url, city_clean):
    soup = BeautifulSoup(html_content, 'html.parser')
    details = {
        "url": school_url,
        "city": city_clean,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }
    
    # 1. Parse JSON-LD blocks
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            if isinstance(data, dict):
                if data.get('@type') == 'School':
                    details["name"] = data.get("name")
                    details["alternate_name"] = data.get("alternateName", "")
                    details["logo_url"] = data.get("logo", "")
                    details["email"] = data.get("email", "")
                    addr = data.get("address")
                    if addr and isinstance(addr, dict):
                        details["address_locality"] = addr.get("addressLocality", "")
                        details["address_region"] = addr.get("addressRegion", "")
                        details["postal_code"] = addr.get("postalCode", "")
                        details["street_address"] = addr.get("streetAddress", "")
                        details["telephone"] = addr.get("telephone", data.get("telephone", ""))
                elif data.get('@type') == 'Place' and data.get('geo'):
                    geo = data['geo']
                    if isinstance(geo, dict):
                        details["latitude"] = clean_float(geo.get("latitude"))
                        details["longitude"] = clean_float(geo.get("longitude"))
        except Exception:
            pass
            
    # Sibling fallback for school name
    if not details.get("name"):
        h1 = soup.find('h1')
        details["name"] = h1.text.strip() if h1 else ""
        
    # Extract Board
    found_board = "Unknown"
    page_text = soup.get_text()
    if "CBSE" in page_text.upper():
        found_board = "CBSE"
    elif "ICSE" in page_text.upper() or "CISCE" in page_text.upper():
        found_board = "ICSE"
    elif "IB" in page_text.upper():
        found_board = "IB"
    elif "IGCSE" in page_text.upper():
        found_board = "IGCSE"
    elif "STATE BOARD" in page_text.upper() or "STATE" in page_text.upper():
        found_board = "State board"
    details["board"] = found_board
    
    # Extract Academic & Key Stats (dynamically parse all .data-list items)
    for dl in soup.find_all(class_='data-list'):
        small = dl.find('small')
        if small:
            key = re.sub(r'[\s\n]+', ' ', small.text).replace('?', '').replace(':', '').strip()
            key = re.sub(r'[^a-zA-Z0-9 ]', '', key).strip()
            value_el = dl.find(class_=lambda c: c in ['text-big', 'ratio-text'] or c is None) or dl.find(['span', 'big', 'div'])
            if value_el:
                val_text = re.sub(r'[\s\n]+', ' ', value_el.text).strip()
                if val_text:
                    normalized_key = re.sub(r'\s+', '_', key.lower())
                    details[normalized_key] = val_text
                    
    # Fallbacks for standard keys
    for k in ["classes_offered", "language_of_instruction", "academic_session", "school_format", "school_type"]:
        details[k] = details.get(k) or ""
        
    # 4. Extract Facilities (only available ones)
    facilities = []
    for li in soup.select('#facilities_tab li, .facilities-list li, [class*="facility"] li'):
        li_class = li.get('class') or []
        li_class_str = " ".join(li_class).lower()
        if 'notavailable' in li_class_str or 'notavaiable' in li_class_str or 'not-available' in li_class_str:
            continue
            
        is_available = True
        for child in li.find_all(class_=True):
            child_class_str = " ".join(child.get('class')).lower()
            if 'notavailable' in child_class_str or 'notavaiable' in child_class_str or 'not-available' in child_class_str:
                is_available = False
                break
        if is_available:
            txt = li.text.strip()
            if txt:
                facilities.append(txt)
    details["facilities"] = ", ".join(facilities)
    
    # 5. Extract Required Documents
    docs = []
    for li in soup.select('ul.custom-list li, .documents-list li'):
        txt = li.text.strip()
        if txt:
            docs.append(txt)
    details["documents_required"] = ", ".join(docs)
    
    # Extract school ID from fees selector data-sid
    fees_select = soup.find('select', id='fees_detail')
    if fees_select and fees_select.get('data-sid'):
        details["school_id"] = fees_select['data-sid']
    else:
        details["school_id"] = "sid_" + str(abs(hash(school_url)))[:7]
        
    return details

def step_discover_uniapply(city_slug, city_clean, force_discover=False):
    print(f"\n=== STAGE 1A: UNIANPLY DISCOVERY ({city_clean}) ===")
    
    os.makedirs("data", exist_ok=True)
    conn = get_db_conn(city_slug)
    init_db(conn)
    
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM schools_discovery")
    count_before = cursor.fetchone()[0]
    
    if count_before > 0 and not force_discover:
        print(f"Skipping discovery. Database already contains {count_before} discovered schools.")
        conn.close()
        return True
        
    if curl_requests is None:
        print("Error: curl_cffi not available. Cannot run UniApply discovery.")
        conn.close()
        return False
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    test_urls = [
        f"https://www.uniapply.com/schools/schools-in-{city_slug}/",
        f"https://www.uniapply.com/schools/in-{city_slug}/"
    ]
    
    base_url = None
    for url in test_urls:
        print(f"Testing UniApply base URL: {url}")
        try:
            r = curl_requests.get(url, headers=headers, impersonate="chrome", timeout=15)
            if r.status_code == 200 and "application/ld+json" in r.text:
                base_url = url
                print(f"  -> Found valid base URL: {base_url}")
                break
        except Exception as e:
            print(f"  -> Error checking base URL: {e}")
            
    if not base_url:
        print(f"Warning: Could not resolve valid UniApply URL for city '{city_clean}'. Discovery skipped.")
        conn.close()
        return True
        
    print(f"Paginating listing pages to discover schools...")
    page_num = 1
    max_pages = 191
    
    while page_num <= max_pages:
        list_url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
        print(f"Scraping listing page {page_num}: {list_url}")
        
        try:
            r = curl_requests.get(list_url, headers=headers, impersonate="chrome", timeout=20)
            if r.status_code != 200:
                print(f"  -> Listing page returned HTTP {r.status_code}. Stopping.")
                break
                
            soup = BeautifulSoup(r.text, 'html.parser')
            page_schools = []
            
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '')
                    if isinstance(data, dict) and data.get('@type') == 'ItemList':
                        elements = data.get('itemListElement', [])
                        for el in elements:
                            if el.get('url') and el.get('name'):
                                page_schools.append((el['url'], el['name']))
                except Exception:
                    pass
                    
            print(f"  -> Discovered {len(page_schools)} schools on page {page_num}.")
            
            if not page_schools:
                print("  -> No schools found on this page. Stopping discovery.")
                break
                
            cursor.execute("BEGIN TRANSACTION")
            inserted = 0
            for url, name in page_schools:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO schools_discovery (url, name, status)
                        VALUES (?, ?, 'pending')
                    """, (url, name))
                    if cursor.rowcount > 0:
                        inserted += 1
                except Exception as e:
                    pass
            conn.commit()
            print(f"  -> Added {inserted} new schools to discovery list.")
            
        except Exception as e:
            print(f"  [Error] Failed to load listing page {page_num}: {e}")
            break
            
        page_num += 1
        time.sleep(random.uniform(1.5, 3.0))
        
    cursor.execute("SELECT COUNT(*) FROM schools_discovery")
    total_discovered = cursor.fetchone()[0]
    print(f"Discovery complete. Total schools in discovery table: {total_discovered}")
    conn.close()
    return True

def step_extract_uniapply(city_slug, city_clean, run_limit=None):
    print(f"\n=== STAGE 1B: UNIANPLY EXTRACTION ({city_clean}) ===")
    
    if curl_requests is None:
        print("Error: curl_cffi not available. Cannot extract details.")
        return False
        
    conn = get_db_conn(city_slug)
    cursor = conn.cursor()
    
    # Get pending schools
    cursor.execute("SELECT url, name FROM schools_discovery WHERE status = 'pending'")
    pending = cursor.fetchall()
    print(f"Found {len(pending)} pending schools to scrape.")
    
    if not pending:
        print("No pending schools to extract.")
        conn.close()
        return True
        
    actual_limit = run_limit if (run_limit and run_limit > 0) else len(pending)
    todo = pending[:actual_limit]
    print(f"Processing up to {len(todo)} schools in this run...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    
    processed_count = 0
    failed_count = 0
    
    for idx, (school_url, school_name) in enumerate(todo):
        print(f"[{idx+1}/{len(todo)}] Scraping details for: {school_name} -> {school_url}")
        
        try:
            session = curl_requests.Session()
            r = session.get(school_url, headers=headers, impersonate="chrome", timeout=20)
            if r.status_code != 200:
                raise Exception(f"Failed to fetch detail page: HTTP {r.status_code}")
                
            details = extract_uniapply_school_details(r.text, school_url, city_clean)
            
            soup = BeautifulSoup(r.text, 'html.parser')
            select_fees = soup.find('select', id='fees_detail')
            csrf_input = soup.find('input', {'name': 'csrfmiddlewaretoken'})
            csrf_token = csrf_input['value'] if csrf_input else None
            
            class_fees_map = {}
            if select_fees and csrf_token:
                sid = select_fees.get('data-sid')
                options = []
                for opt in select_fees.find_all('option'):
                    val = opt.get('value')
                    txt = opt.text.strip()
                    if val and val.isdigit():
                        options.append((val, txt))
                        
                if sid:
                    for val, txt in options:
                        post_url = 'https://www.uniapply.com/institute/show-fees'
                        post_headers = {
                            'Referer': school_url,
                            'X-Requested-With': 'XMLHttpRequest',
                            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        }
                        data = {
                            'sid': sid,
                            'class_id': val,
                            'stream_id': '0',
                            'csrfmiddlewaretoken': csrf_token
                        }
                        
                        time.sleep(random.uniform(0.3, 0.6))
                        try:
                            r_fees = session.post(post_url, data=data, headers=post_headers, impersonate="chrome", timeout=10)
                            if r_fees.status_code == 200:
                                parsed = parse_fees_html_python(r_fees.text)
                                class_fees_map[txt] = {
                                    "class_id": val,
                                    "total_cost": parsed["total_cost"],
                                    "monthly_cost": parsed["monthly_cost"],
                                    "period": parsed["period"],
                                    "components": parsed["components"],
                                    "notes": parsed["notes"]
                                }
                        except Exception as e_fee:
                            pass
            
            evolve_schema(conn, details)
            
            cols = ["school_id", "name", "url", "city", "raw_details_json", "raw_fees_json"]
            vals = [details["school_id"], details["name"], details["url"], details["city"], json.dumps(details), json.dumps(class_fees_map)]
            
            cursor.execute("PRAGMA table_info(school_details)")
            table_info = cursor.fetchall()
            existing_cols = [row[1] for row in table_info]
            
            dynamic_cols = []
            dynamic_vals = []
            for col in existing_cols:
                col_lower = col.lower()
                if col_lower not in cols and col_lower in details:
                    dynamic_cols.append(col)
                    dynamic_vals.append(details[col_lower])
                    
            insert_cols = cols + dynamic_cols
            insert_vals = vals + dynamic_vals
            placeholders = ", ".join(["?" for _ in range(len(insert_vals))])
            
            cursor.execute("BEGIN TRANSACTION")
            cursor.execute(f"""
                INSERT OR REPLACE INTO school_details ({", ".join(insert_cols)})
                VALUES ({placeholders})
            """, insert_vals)
            
            cursor.execute("""
                UPDATE schools_discovery
                SET status = 'processed', error_message = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE url = ?
            """, (school_url,))
            conn.commit()
            
            processed_count += 1
            print(f"  -> Scraped & saved {details['name']} with {len(class_fees_map)} classes.")
            
        except Exception as e:
            cursor.execute("ROLLBACK")
            cursor.execute("""
                UPDATE schools_discovery
                SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE url = ?
            """, (str(e), school_url))
            conn.commit()
            failed_count += 1
            print(f"  -> [Error] Failed to scrape {school_name}: {e}")
            
        time.sleep(random.uniform(1.5, 3.0))
        
    conn.close()
    print(f"Deep extraction complete. Scraped: {processed_count} | Failed: {failed_count}")
    return True

# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Stage 1C: Scrape & Merge Ezyschooling API
# ─────────────────────────────────────────────────────────────────────────────

def step_scrape_ezyschooling_api(city_slug, city_clean, force_download=False):
    print(f"\n=== STAGE 1: SCRAPING EZYSCHOOLING API DATA & MERGING UNIANPLY ({city_clean}) ===")
    
    os.makedirs("data", exist_ok=True)
    raw_json_path = f"data/ezyschooling_raw_{city_slug}.json"
    summary_json_path = f"data/school_averages_summary_{city_slug}.json"
    summary_csv_path = f"data/school_averages_summary_{city_slug}.csv"
    
    raw_schools = []
    
    if os.path.exists(raw_json_path) and not force_download:
        print(f"Loading cached Ezyschooling raw data from {raw_json_path}...")
        with open(raw_json_path, 'r', encoding='utf-8') as f:
            raw_schools = json.load(f)
        print(f"Loaded {len(raw_schools)} schools from cache.")
    else:
        if curl_requests is None:
            print("Error: curl_cffi module not found. Cannot perform live API scraping. Please install it first.")
            return False
            
        print(f"Scraping Ezyschooling API for {city_clean}...")
        url = "https://api.main.ezyschooling.com/api/v1/schools/document/"
        limit = 100
        offset = 0
        total_count = 1
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://ezyschooling.com",
            "Referer": "https://ezyschooling.com/"
        }
        
        while offset < total_count:
            params = {
                "is_active": "true",
                "is_verified": "true",
                "limit": str(limit),
                "offset": str(offset),
                "ordering": "-fees",
                "school_city": city_slug,
                "school_city__exclude": "delhi,boarding-schools,online-schools",
                "session": "2026-2027"
            }
            
            print(f"Fetching offset {offset} (Total count resolved: {total_count})...")
            try:
                r = curl_requests.get(url, params=params, headers=headers, impersonate="chrome", timeout=20)
                if r.status_code == 200:
                    data = r.json()
                    total_count = data.get("count", total_count)
                    results = data.get("results", [])
                    raw_schools.extend(results)
                    print(f" -> Extracted {len(results)} schools. Total in list: {len(raw_schools)}.")
                    
                    if not results:
                        break
                else:
                    print(f" [Error] API returned status {r.status_code}. Aborting API loop.")
                    break
            except Exception as e:
                print(f" [Error] Request failed at offset {offset}: {e}")
                break
                
            offset += limit
            time.sleep(random.uniform(1.5, 3.0))
            
        if raw_schools:
            with open(raw_json_path, 'w', encoding='utf-8') as f:
                json.dump(raw_schools, f, indent=2)
            print(f"Saved raw data to {raw_json_path}.")
            
    # Load UniApply schools from SQLite
    uniapply_schools = []
    db_path = f"data/school_scraping_{city_slug}.db"
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='school_details'")
            if cursor.fetchone():
                cursor.execute("SELECT name, url, raw_details_json, raw_fees_json FROM school_details")
                rows = cursor.fetchall()
                for r_name, r_url, r_details, r_fees in rows:
                    try:
                        details = json.loads(r_details) if r_details else {}
                    except Exception:
                        details = {}
                    try:
                        fees_map = json.loads(r_fees) if r_fees else {}
                    except Exception:
                        fees_map = {}
                    
                    uniapply_schools.append({
                        "name": r_name,
                        "url": r_url,
                        "details": details,
                        "fees_map": fees_map
                    })
            conn.close()
            print(f"Loaded {len(uniapply_schools)} schools from UniApply SQLite database.")
        except Exception as e_db:
            print(f"Warning: Failed to load UniApply data from database: {e_db}")
            
    # Merge logic
    merged_schools = []
    matched_uniapply_indices = set()
    
    fallback_ratio = 22.97
    fallback_teachers = 28.98
    fallback_student_count = round(fallback_ratio * fallback_teachers, 1)
    
    # Pre-calculate normalized names for UniApply schools
    uniapply_normalized = []
    for ua in uniapply_schools:
        uniapply_normalized.append(normalize_name_es(ua["name"]))
        
    for es in raw_schools:
        es_name = es.get("name", "")
        es_coords = es.get("geocoords", {})
        es_lat = clean_float(es_coords.get("lat"))
        es_lon = clean_float(es_coords.get("lon"))
        es_zip = es.get("zipcode")
        es_addr = es.get("street_address", "")
        es_fee = parse_ezyschooling_fee_val(es)
        es_start, es_end = parse_classes_es(es.get("offered_classes", ""))
        es_board = normalize_board_es(es.get("school_boardss", []))
        
        es_ratio_str = es.get("student_teacher_ratio", "NA")
        es_ratio = es_ratio_str if (es_ratio_str and es_ratio_str != "NA" and ":" in es_ratio_str) else "NA"
        es_url = f"https://ezyschooling.com/school/{es.get('slug')}"
        
        # Try to find a match in UniApply
        best_ua_idx = None
        es_norm = normalize_name_es(es_name)
        
        for idx, ua in enumerate(uniapply_schools):
            if idx in matched_uniapply_indices:
                continue
                
            ua_norm = uniapply_normalized[idx]
            
            # 1. Exact match
            if es_norm == ua_norm and es_norm:
                best_ua_idx = idx
                break
                
            # 2. High Jaccard similarity
            jac = word_jaccard(es_norm, ua_norm)
            if jac >= 0.7:
                best_ua_idx = idx
                break
                
            # 3. Geodistance match
            ua_lat = ua["details"].get("latitude")
            ua_lon = ua["details"].get("longitude")
            if es_lat and es_lon and ua_lat and ua_lon:
                dist = haversine_distance(es_lat, es_lon, ua_lat, ua_lon)
                if dist < 150.0 and jac >= 0.3:
                    best_ua_idx = idx
                    break
                    
        if best_ua_idx is not None:
            matched_uniapply_indices.add(best_ua_idx)
            ua = uniapply_schools[best_ua_idx]
            ua_details = ua["details"]
            ua_fees_map = ua["fees_map"]
            
            # Merge fields
            merged_name = es_name # Prefer Ezyschooling name for overrides compatibility
            
            # Board
            ua_board = ua_details.get("board", "Unknown")
            merged_board = ua_board if ua_board != "Unknown" else es_board
            
            # URL: use Ezyschooling URL
            merged_url = es_url
            
            # Ratio & Teacher count
            ua_ratio = parse_uniapply_ratio(ua_details)
            merged_ratio = ua_ratio if ua_ratio != "NA" else es_ratio
            
            merged_teachers = parse_uniapply_teacher_count(ua_details)
            
            # Fees
            ua_fee = parse_uniapply_fees(ua_fees_map)
            merged_fee = ua_fee if ua_fee != "NA" else es_fee
            
            # Classes
            ua_start, ua_end = parse_uniapply_classes(ua_details, ua_fees_map)
            merged_start = ua_start if ua_start != "NA" else es_start
            merged_end = ua_end if ua_end != "NA" else es_end
            
            # Address & Pincode
            ua_zip = ua_details.get("postal_code")
            ua_addr = ua_details.get("street_address") or ua_details.get("address_locality")
            merged_zip = ua_zip if (ua_zip and ua_zip != "NA") else (es_zip if es_zip else "NA")
            merged_addr = ua_addr if (ua_addr and ua_addr != "NA") else (es_addr if es_addr else "NA")
            
            # Coordinates
            ua_lat = ua_details.get("latitude")
            ua_lon = ua_details.get("longitude")
            merged_lat = ua_lat if ua_lat else (es_lat if es_lat else "NA")
            merged_lon = ua_lon if ua_lon else (es_lon if es_lon else "NA")
            
            new_school = {
                "School Name": merged_name,
                "Board": merged_board,
                "URL": merged_url,
                "Student-Teacher Ratio": merged_ratio,
                "Teacher Count": merged_teachers,
                "Computed Student Count": fallback_student_count,
                "Is Student Count Estimated": "Yes",
                "Average Fee (Annual)": merged_fee,
                "Is Fee Estimated": "No" if merged_fee != "NA" else "Yes",
                "Starting Class": merged_start,
                "Ending Class": merged_end,
                "Address": merged_addr,
                "Pincode": merged_zip,
                "Latitude": merged_lat,
                "Longitude": merged_lon
            }
            merged_schools.append(new_school)
        else:
            # Add Ezyschooling only
            new_school = {
                "School Name": es_name,
                "Board": es_board,
                "URL": es_url,
                "Student-Teacher Ratio": es_ratio,
                "Teacher Count": "NA",
                "Computed Student Count": fallback_student_count,
                "Is Student Count Estimated": "Yes",
                "Average Fee (Annual)": es_fee,
                "Is Fee Estimated": "No" if es_fee != "NA" else "Yes",
                "Starting Class": es_start,
                "Ending Class": es_end,
                "Address": es_addr if es_addr else "NA",
                "Pincode": es_zip if es_zip else "NA",
                "Latitude": es_lat if es_lat else "NA",
                "Longitude": es_lon if es_lon else "NA"
            }
            merged_schools.append(new_school)
            
    # Add unmatched UniApply schools
    unmatched_count = 0
    for idx, ua in enumerate(uniapply_schools):
        if idx in matched_uniapply_indices:
            continue
            
        ua_details = ua["details"]
        ua_fees_map = ua["fees_map"]
        
        ua_ratio = parse_uniapply_ratio(ua_details)
        ua_teachers = parse_uniapply_teacher_count(ua_details)
        ua_fee = parse_uniapply_fees(ua_fees_map)
        ua_start, ua_end = parse_uniapply_classes(ua_details, ua_fees_map)
        ua_zip = ua_details.get("postal_code") or "NA"
        ua_addr = ua_details.get("street_address") or ua_details.get("address_locality") or "NA"
        ua_lat = ua_details.get("latitude") or "NA"
        ua_lon = ua_details.get("longitude") or "NA"
        
        new_school = {
            "School Name": ua["name"],
            "Board": ua_details.get("board", "Unknown"),
            "URL": ua["url"],
            "Student-Teacher Ratio": ua_ratio,
            "Teacher Count": ua_teachers,
            "Computed Student Count": fallback_student_count,
            "Is Student Count Estimated": "Yes",
            "Average Fee (Annual)": ua_fee,
            "Is Fee Estimated": "No" if ua_fee != "NA" else "Yes",
            "Starting Class": ua_start,
            "Ending Class": ua_end,
            "Address": ua_addr,
            "Pincode": ua_zip,
            "Latitude": ua_lat,
            "Longitude": ua_lon
        }
        merged_schools.append(new_school)
        unmatched_count += 1
        
    print(f"Merged schools list contains {len(merged_schools)} total schools ({unmatched_count} unique to UniApply).")
    
    print(f"Exporting initial summaries ({len(merged_schools)} schools) to JSON and CSV...")
    with open(summary_json_path, 'w', encoding='utf-8') as f:
        json.dump(merged_schools, f, indent=2)
    with open("data/school_averages_summary.json", 'w', encoding='utf-8') as f:
        json.dump(merged_schools, f, indent=2)
        
    fieldnames = [
        'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
        'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
        'Average Fee (Annual)', 'Is Fee Estimated', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
    ]
    with open(summary_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_schools)
    with open("data/school_averages_summary.csv", 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_schools)
        
    print("Initial summary setup & merge complete.")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Stage 2: Geocoding via Nominatim
# ─────────────────────────────────────────────────────────────────────────────

def format_address(addr, display_name, city_clean):
    road = addr.get("road") or addr.get("suburb") or addr.get("neighbourhood")
    village = addr.get("village") or addr.get("suburb") or addr.get("city_district") or addr.get("commercial")
    county = addr.get("county") or addr.get("state_district")
    
    parts = []
    if road: parts.append(road)
    if village: parts.append(village)
    if county: parts.append(county)
    parts.append(city_clean)
    
    formatted = ", ".join(parts)
    return formatted if len(formatted) > len(city_clean) + 5 else display_name

def extract_pincode(addr, display_name):
    postcode = addr.get("postcode")
    if postcode and postcode.isdigit() and len(postcode) == 6:
        return postcode
    matches = re.findall(r'\b\d{6}\b', display_name)
    return matches[0] if matches else None

def step_geocode(city_slug, city_clean):
    print(f"\n=== STAGE 2: GEOCODING PLACES VIA NOMINATIM ({city_clean}) ===")
    
    json_path = f"data/school_averages_summary_{city_slug}.json"
    csv_path = f"data/school_averages_summary_{city_slug}.csv"
    cache_path = f"data/geocoding_cache_{city_slug}.json"
    
    if not os.path.exists(json_path):
        print("Error: Missing summary file. Run API step first.")
        return False
        
    with open(json_path, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)
        
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached geocoding records.")
        except Exception:
            pass
            
    headers = {
        "User-Agent": f"SchoolDataEnrichmentAgent/1.0 (contact: admin@{city_slug}schoolinfo.org) Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json"
    }
    
    geocoded_count = 0
    cache_hits = 0
    
    for idx, school in enumerate(summary_data):
        school_name = school.get("School Name")
        lat = school.get("Latitude", "NA")
        lon = school.get("Longitude", "NA")
        addr = school.get("Address", "NA")
        pin = school.get("Pincode", "NA")
        
        # Reverse Geocode
        if (not addr or addr == "NA" or not pin or pin == "NA") and lat != "NA" and lon != "NA":
            cache_key = f"rev:{lat},{lon}"
            
            if cache_key in cache:
                cached = cache[cache_key]
                school["Address"] = cached.get("address", "NA")
                school["Pincode"] = cached.get("pincode", "NA")
                cache_hits += 1
            else:
                print(f"[{idx+1}/{len(summary_data)}] Reverse geocoding ({lat}, {lon}) for {school_name}...")
                osm_url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}"
                try:
                    r = requests.get(osm_url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        addr_dict = data.get("address", {})
                        display_name = data.get("display_name", "")
                        
                        resolved_pin = extract_pincode(addr_dict, display_name) or "NA"
                        resolved_addr = format_address(addr_dict, display_name, city_clean)
                        
                        school["Address"] = resolved_addr
                        school["Pincode"] = resolved_pin
                        
                        cache[cache_key] = {
                            "address": resolved_addr,
                            "pincode": resolved_pin,
                            "raw": data
                        }
                        with open(cache_path, 'w', encoding='utf-8') as cf:
                            json.dump(cache, cf, indent=2)
                        geocoded_count += 1
                        print(f"  -> Resolved Address: {resolved_addr} | Pincode: {resolved_pin}")
                    else:
                        print(f"  [Warning] OSM API returned HTTP {r.status_code}")
                except Exception as e:
                    print(f"  [Error] Request failed: {e}")
                time.sleep(1.5)
                
        # Forward Geocode
        if (lat == "NA" or lon == "NA") and pin and pin != "NA":
            cache_key = f"fwd:{school_name}:{pin}"
            
            if cache_key in cache:
                cached = cache[cache_key]
                school["Latitude"] = cached.get("lat", "NA")
                school["Longitude"] = cached.get("lon", "NA")
                cache_hits += 1
            else:
                print(f"[{idx+1}/{len(summary_data)}] Forward geocoding coordinates for {school_name} (Pincode: {pin})...")
                osm_url = f"https://nominatim.openstreetmap.org/search?format=jsonv2&q={urllib.parse.quote(school_name)}, {pin}, India&limit=1"
                try:
                    r = requests.get(osm_url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        if data:
                            flat = float(data[0].get("lat"))
                            flon = float(data[0].get("lon"))
                            school["Latitude"] = flat
                            school["Longitude"] = flon
                            
                            cache[cache_key] = {"lat": flat, "lon": flon, "raw": data}
                            with open(cache_path, 'w', encoding='utf-8') as cf:
                                json.dump(cache, cf, indent=2)
                            geocoded_count += 1
                            print(f"  -> Resolved Coordinates: {flat}, {flon}")
                        else:
                            print(f"  -> No search results found.")
                    else:
                        print(f"  [Warning] OSM API returned HTTP {r.status_code}")
                except Exception as e:
                    print(f"  [Error] Request failed: {e}")
                time.sleep(1.5)
                
    print("\nSaving updated summaries...")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2)
    with open("data/school_averages_summary.json", 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, indent=2)
        
    fieldnames = [
        'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
        'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
        'Average Fee (Annual)', 'Is Fee Estimated', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
    ]
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_data)
    with open("data/school_averages_summary.csv", 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_data)
        
    print(f"Geocoding Stats:")
    print(f" - Newly Geocoded Locations: {geocoded_count}")
    print(f" - Loaded from cache: {cache_hits}")
    return True

# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Stage 3: Enrich CBSE/ICSE Fees via Ezyschooling
# ─────────────────────────────────────────────────────────────────────────────

def step_enrich_ezyschooling(city_slug, city_clean, run_limit=5, delay_min=4, delay_max=8):
    print(f"\n=== STAGE 3: ENRICHING CBSE/ICSE FEES VIA EZYSCHOOLING ===")
    
    if curl_requests is None:
        print("Error: curl_cffi module not found. Skipping alternate fees search.")
        return False
        
    json_path = f"data/school_averages_summary_{city_slug}.json"
    csv_path = f"data/school_averages_summary_{city_slug}.csv"
    discovered_path = f"data/discovered_alternate_fees_{city_slug}.json"
    
    if not os.path.exists(json_path):
        print("Error: Summary JSON not found.")
        return False
        
    with open(json_path, 'r', encoding='utf-8') as f:
        schools = json.load(f)
        
    missing_schools = [s for s in schools if s.get("Board") in ["CBSE", "ICSE"] and s.get("Average Fee (Annual)") == "NA"]
    print(f"Total CBSE/ICSE schools missing fee details: {len(missing_schools)}")
    
    if not missing_schools:
        print("No missing CBSE/ICSE fees to enrich.")
        return True
        
    discovered = {}
    if os.path.exists(discovered_path):
        try:
            with open(discovered_path, 'r', encoding='utf-8') as f:
                discovered = json.load(f)
        except Exception:
            pass
            
    todo = [s for s in missing_schools if s["School Name"] not in discovered]
    print(f"Pending verification/search: {len(todo)}")
    
    if not todo:
        print("All pending CBSE/ICSE schools already searched.")
        return True
        
    actual_limit = min(run_limit, len(todo))
    print(f"Processing up to {actual_limit} schools in this run...")
    
    success_count = 0
    
    for i, school in enumerate(todo[:actual_limit]):
        name = school["School Name"]
        clean_name = clean_school_name_query(name)
        query = f"{clean_name} {city_clean} ezyschooling"
        
        print(f"[{i+1}/{actual_limit}] Searching for: '{query}'")
        links = search_yahoo_ezyschooling(query, city_clean)
        
        fee_info = None
        if links:
            filtered_links = [l for l in links if city_slug in l.lower() or city_clean.lower() in l.lower()]
            if not filtered_links:
                print(f"  [Warning] Found {len(links)} candidate links, but none matched the city '{city_clean}' in their URL slug. Mismatch check triggered.")
                discovered[name] = {"status": "City Mismatch", "uniapply_url": school.get("URL"), "query": query, "links_found": links}
                continue
                
            print(f"  Found {len(filtered_links)} valid city links. Scraping first...")
            for link in filtered_links:
                time.sleep(random.uniform(1.5, 3))
                info = scrape_ezyschooling_fees(link)
                if info and info.get("average_fee") is not None:
                    fee_info = info
                    print(f"    -> Extracted Fee Average: ₹{info['average_fee']:,} (from {info['fee_count']} classes)")
                    break
        else:
            print("  No candidate links resolved on Yahoo.")
            
        if fee_info:
            discovered[name] = {
                "status": "Found",
                "uniapply_url": school.get("URL"),
                "query": query,
                "ezyschooling_url": fee_info["url"],
                "average_fee": fee_info["average_fee"],
                "class_count": fee_info["fee_count"],
                "scraped_fees": fee_info["valid_fees"]
            }
            school["Average Fee (Annual)"] = fee_info["average_fee"]
            school["Is Fee Estimated"] = "No"
            success_count += 1
        else:
            if name not in discovered or discovered[name].get("status") != "City Mismatch":
                discovered[name] = {
                    "status": "Not Found",
                    "uniapply_url": school.get("URL"),
                    "query": query
                }
                
        with open(discovered_path, 'w', encoding='utf-8') as f:
            json.dump(discovered, f, indent=2)
            
        if i < actual_limit - 1:
            delay = random.uniform(delay_min, delay_max)
            print(f"  Waiting {delay:.1f}s to be polite...")
            time.sleep(delay)
            
    if success_count > 0:
        print(f"\nMerged {success_count} alternate fees back into summaries.")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(schools, f, indent=2)
        with open("data/school_averages_summary.json", 'w', encoding='utf-8') as f:
            json.dump(schools, f, indent=2)
            
        fieldnames = [
            'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
            'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
            'Average Fee (Annual)', 'Is Fee Estimated', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
        ]
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(schools)
        with open("data/school_averages_summary.csv", 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(schools)
            
    return True

# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Stage 4: Enrich Remaining Fees via Edustoke
# ─────────────────────────────────────────────────────────────────────────────

def step_enrich_edustoke(city_slug, city_clean, run_limit=5, delay_min=4, delay_max=8):
    print(f"\n=== STAGE 4: ENRICHING REMAINING FEES VIA EDUSTOKE ===")
    
    if curl_requests is None:
        print("Error: curl_cffi module not found. Skipping alternate fees search.")
        return False
        
    json_path = f"data/school_averages_summary_{city_slug}.json"
    csv_path = f"data/school_averages_summary_{city_slug}.csv"
    discovered_path = f"data/discovered_fees_{city_slug}.json"
    
    if not os.path.exists(json_path):
        print("Error: Summary JSON not found.")
        return False
        
    with open(json_path, 'r', encoding='utf-8') as f:
        schools = json.load(f)
        
    missing_schools = [s for s in schools if s.get("Average Fee (Annual)") == "NA"]
    print(f"Total schools missing fee details: {len(missing_schools)}")
    
    if not missing_schools:
        print("No missing fees to enrich.")
        return True
        
    discovered = {}
    if os.path.exists(discovered_path):
        try:
            with open(discovered_path, 'r', encoding='utf-8') as f:
                discovered = json.load(f)
        except Exception:
            pass
            
    todo = [s for s in missing_schools if s["School Name"] not in discovered]
    print(f"Pending verification/search: {len(todo)}")
    
    if not todo:
        print("All pending schools already searched.")
        return True
        
    actual_limit = min(run_limit, len(todo))
    print(f"Processing up to {actual_limit} schools in this run...")
    
    success_count = 0
    
    for i, school in enumerate(todo[:actual_limit]):
        name = school["School Name"]
        clean_name = clean_school_name_query(name)
        query = f"{clean_name} {city_clean} edustoke"
        
        print(f"[{i+1}/{actual_limit}] Searching for: '{query}'")
        links = search_yahoo_edustoke(query)
        
        fee_info = None
        if links:
            filtered_links = [l for l in links if city_slug in l.lower() or city_clean.lower() in l.lower()]
            if not filtered_links:
                print(f"  [Warning] Found {len(links)} candidate links, but none matched target city '{city_clean}'. City mismatch triggered.")
                discovered[name] = {"status": "City Mismatch", "uniapply_url": school.get("URL"), "query": query, "links_found": links}
                continue
                
            print(f"  Found {len(filtered_links)} valid city links. Scraping first...")
            for link in filtered_links:
                time.sleep(random.uniform(1.5, 3))
                info = scrape_edustoke_fees(link)
                if info and info.get("total_fee") is not None:
                    fee_info = info
                    print(f"    -> Extracted Fee: {info['total_fee']}")
                    break
        else:
            print("  No candidate links resolved on Yahoo.")
            
        if fee_info:
            discovered[name] = {
                "status": "Found",
                "uniapply_url": school.get("URL"),
                "query": query,
                "edustoke_url": fee_info["url"],
                "total_fee": fee_info["total_fee"]
            }
            school["Average Fee (Annual)"] = fee_info["total_fee"]
            school["Is Fee Estimated"] = "No"
            success_count += 1
        else:
            if name not in discovered or discovered[name].get("status") != "City Mismatch":
                discovered[name] = {
                    "status": "Not Found",
                    "uniapply_url": school.get("URL"),
                    "query": query
                }
                
        with open(discovered_path, 'w', encoding='utf-8') as f:
            json.dump(discovered, f, indent=2)
            
        if i < actual_limit - 1:
            delay = random.uniform(delay_min, delay_max)
            print(f"  Waiting {delay:.1f}s to be polite...")
            time.sleep(delay)
            
    if success_count > 0:
        print(f"\nMerged {success_count} alternate fees back into summaries.")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(schools, f, indent=2)
        with open("data/school_averages_summary.json", 'w', encoding='utf-8') as f:
            json.dump(schools, f, indent=2)
            
        fieldnames = [
            'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
            'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
            'Average Fee (Annual)', 'Is Fee Estimated', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
        ]
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(schools)
        with open("data/school_averages_summary.csv", 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(schools)
            
    print("Edustoke enrichment stage completed.")
    return True

# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Stage 5: Post-Processing & Board Imputation
# ─────────────────────────────────────────────────────────────────────────────

def step_process(city_slug, city_clean):
    print(f"\n=== STAGE 5: PROCESSING & IMPUTING DATA ({city_clean}) ===")
    
    json_path = f"data/school_averages_summary_{city_slug}.json"
    csv_path = f"data/school_averages_summary_{city_slug}.csv"
    
    if not os.path.exists(json_path):
        print(f"Error: Target summary file not found at {json_path}. Run API discovery step first.")
        return False
        
    with open(json_path, 'r', encoding='utf-8') as f:
        summary_data = json.load(f)
        
    # Preserve/Load manual overrides if any
    existing_fees = {}
    for s in summary_data:
        fee = s.get("Average Fee (Annual)")
        is_est = s.get("Is Fee Estimated")
        if fee != "NA" and fee is not None and is_est != "Yes":
            try:
                val = float(fee)
                if val > 0:
                    existing_fees[s.get("URL")] = val
            except ValueError:
                pass
            
    # Load alternate fees from discovered files
    alt_fees = {}
    
    # 1. From Ezyschooling discovered files
    ezyschooling_paths = [f"data/discovered_alternate_fees_{city_slug}.json", "discovered_alternate_fees.json"]
    for p in ezyschooling_paths:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for name, info in data.items():
                        if info.get("status") == "Found" and info.get("average_fee") is not None:
                            val = float(info["average_fee"])
                            if val > 0:
                                alt_fees[name] = val
            except Exception:
                pass
                
    # 2. From Edustoke discovered files
    edustoke_paths = [f"data/discovered_fees_{city_slug}.json", "discovered_fees.json"]
    for p in edustoke_paths:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for name, info in data.items():
                        if info.get("status") == "Found" and info.get("total_fee") is not None:
                            val = float(info["total_fee"])
                            if val > 0:
                                alt_fees[name] = val
            except Exception:
                pass

    # Collect ratios and teacher counts for overall city averages (for fallback student counts)
    ratios = []
    teachers_counts = []
    for s in summary_data:
        rat = s.get("Student-Teacher Ratio")
        if rat and rat != "NA":
            try:
                ratios.append(float(rat.split(':')[0]))
            except Exception:
                pass
        tc = s.get("Teacher Count")
        if tc and tc != "NA":
            try:
                teachers_counts.append(float(tc))
            except Exception:
                pass
                
    overall_avg_ratio = mean(ratios) if ratios else 22.97
    overall_avg_teachers = mean(teachers_counts) if teachers_counts else 28.98
    fallback_student_count = round(overall_avg_ratio * overall_avg_teachers, 1)

    # Process each school to update student counts and fees
    for s in summary_data:
        name = s.get("School Name")
        url = s.get("URL")
        
        # Update student count
        rat_str = s.get("Student-Teacher Ratio", "NA")
        tc_str = s.get("Teacher Count", "NA")
        
        try:
            rat = float(rat_str.split(':')[0]) if rat_str != "NA" else None
            tc = float(tc_str) if tc_str != "NA" else None
        except Exception:
            rat, tc = None, None
            
        if rat is not None and tc is not None:
            s["Computed Student Count"] = round(rat * tc, 1)
            s["Is Student Count Estimated"] = "No"
        else:
            s["Computed Student Count"] = fallback_student_count
            s["Is Student Count Estimated"] = "Yes"
            
        # Update fee based on fallback priority
        fee = s.get("Average Fee (Annual)", "NA")
        is_est = s.get("Is Fee Estimated", "No")
        
        if is_est == "Yes":
            fee = "NA"
            
        if fee == "NA" or fee is None:
            if name in alt_fees:
                fee = alt_fees[name]
                
        if (fee == "NA" or fee is None) and url in existing_fees:
            fee = existing_fees[url]
            
        s["Average Fee (Annual)"] = fee

    # Deduplicate schools by URL
    seen_urls = set()
    deduped_results = []
    for s in summary_data:
        url = s.get("URL")
        if url not in seen_urls:
            seen_urls.add(url)
            deduped_results.append(s)

    # Calculate board-wise median fees across all schools with valid fee data
    board_fees = {}
    all_valid_fees = []
    for s in deduped_results:
        fee = s.get("Average Fee (Annual)")
        if fee != "NA" and fee is not None:
            try:
                val = float(fee)
                if val > 0:
                    all_valid_fees.append(val)
                    board = s.get("Board", "Unknown")
                    if board not in board_fees:
                        board_fees[board] = []
                    board_fees[board].append(val)
            except ValueError:
                pass

    city_wide_median = round(median(all_valid_fees), 2) if all_valid_fees else 50000.0
    
    board_medians = {}
    for board, fees in board_fees.items():
        if len(fees) >= 3:
            board_medians[board] = round(median(fees), 2)
        else:
            board_medians[board] = city_wide_median

    # Apply board-wise imputation for missing fees
    imputed_count = 0
    for s in deduped_results:
        fee = s.get("Average Fee (Annual)")
        if fee == "NA" or fee is None or float(fee) <= 0:
            board = s.get("Board", "Unknown")
            imputed_fee = board_medians.get(board, city_wide_median)
            s["Average Fee (Annual)"] = imputed_fee
            s["Is Fee Estimated"] = "Yes"
            imputed_count += 1
        else:
            s["Is Fee Estimated"] = "No"
            
    if imputed_count > 0:
        print(f"Imputed {imputed_count} missing school fees using board-specific median values.")

    print(f"Exporting summary data ({len(deduped_results)} schools) to JSON and CSV...")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(deduped_results, f, indent=2)
        
    fieldnames = [
        'School Name', 'Board', 'URL', 'Student-Teacher Ratio', 
        'Teacher Count', 'Computed Student Count', 'Is Student Count Estimated', 
        'Average Fee (Annual)', 'Is Fee Estimated', 'Starting Class', 'Ending Class', 'Address', 'Pincode', 'Latitude', 'Longitude'
    ]
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped_results)
        
    with open("data/school_averages_summary.json", 'w', encoding='utf-8') as f:
        json.dump(deduped_results, f, indent=2)
    with open("data/school_averages_summary.csv", 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped_results)
        
    print("Summary generation complete.")
    return True

# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Stage 6: Statistics & Reporting
# ─────────────────────────────────────────────────────────────────────────────

def step_stats(city_slug):
    print(f"\n=== STAGE 6: DATA STATISTICS & SUMMARY ({city_slug.upper()}) ===")
    json_path = f"data/school_averages_summary_{city_slug}.json"
    if not os.path.exists(json_path):
        json_path = "data/school_averages_summary.json"
        
    if not os.path.exists(json_path):
        print(f"Error: JSON summary not found at {json_path}")
        return False
        
    with open(json_path, 'r', encoding='utf-8') as f:
        schools = json.load(f)
        
    total_schools = len(schools)
    print(f"Total Schools in Dataset: {total_schools}")
    
    total_students = 0.0
    estimated_count = 0
    actual_count = 0
    
    valid_fees = []
    missing_fees = 0
    
    boards_data = {}
    
    missing_address = 0
    missing_pincode = 0
    missing_coords = 0
    
    for s in schools:
        sc = s.get("Computed Student Count")
        if sc and sc != "NA":
            total_students += float(sc)
            if s.get("Is Student Count Estimated") == "Yes":
                estimated_count += 1
            else:
                actual_count += 1
                
        fee = s.get("Average Fee (Annual)")
        if fee and fee != "NA":
            try:
                val = float(fee)
                if val > 0:
                    valid_fees.append(val)
            except ValueError:
                pass
        else:
            missing_fees += 1
            
        board = s.get("Board", "Unknown")
        if board not in boards_data:
            boards_data[board] = {"count": 0, "students": 0.0, "fees": []}
        boards_data[board]["count"] += 1
        if sc and sc != "NA":
            boards_data[board]["students"] += float(sc)
        if fee and fee != "NA":
            try:
                val = float(fee)
                if val > 0:
                    boards_data[board]["fees"].append(val)
            except ValueError:
                pass
                
        addr = s.get("Address")
        pin = s.get("Pincode")
        lat = s.get("Latitude")
        lon = s.get("Longitude")
        
        if not addr or addr == "NA" or addr == "None":
            missing_address += 1
        if not pin or pin == "NA" or pin == "None":
            missing_pincode += 1
        if lat == "NA" or lon == "NA" or lat is None or lon is None:
            missing_coords += 1
            
    print(f"Total Computed Students: {int(total_students):,}")
    print(f" - From Actual Data: {actual_count} schools")
    print(f" - From Fallback Estimates: {estimated_count} schools")
    
    print(f"\nFee Statistics (across {len(valid_fees)} schools with valid fee data):")
    if valid_fees:
        print(f" - Average Fee (Annual): Rs.{mean(valid_fees):,.2f}")
        print(f" - Median Fee (Annual): Rs.{median(valid_fees):,.2f}")
        print(f" - Max Fee (Annual): Rs.{max(valid_fees):,.2f}")
        print(f" - Min Fee (Annual): Rs.{min(valid_fees):,.2f}")
    print(f" - Schools with missing fees: {missing_fees} ({missing_fees/total_schools*100:.1f}%)")
    
    print(f"\nGeocoding Coverage:")
    print(f" - Schools missing Address: {missing_address} ({missing_address/total_schools*100:.1f}%)")
    print(f" - Schools missing Pincode: {missing_pincode} ({missing_pincode/total_schools*100:.1f}%)")
    print(f" - Schools missing Coordinates: {missing_coords} ({missing_coords/total_schools*100:.1f}%)")
    
    print(f"\nBoard-wise Breakdown:")
    print(f"{'Board':<25} | {'School Count':<12} | {'Total Students':<14} | {'Average Fee':<15}")
    print("-" * 75)
    for board, data in sorted(boards_data.items(), key=lambda x: x[1]["count"], reverse=True):
        avg_fee_str = "NA"
        if data["fees"]:
            avg_fee_str = f"Rs.{mean(data['fees']):,.2f}"
        print(f"{board:<25} | {data['count']:<12} | {int(data['students']):<14,} | {avg_fee_str:<15}")
        
    return True

# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline Stage 7: Clean Up Temporary/Intermediate Files
# ─────────────────────────────────────────────────────────────────────────────

def step_cleanup(city_slug):
    print(f"\n=== STAGE 7: CLEANING UP INTERMEDIATE CACHES ({city_slug.upper()}) ===")
    files_to_delete = [
        f"data/ezyschooling_raw_{city_slug}.json",
        f"data/geocoding_cache_{city_slug}.json",
        f"data/discovered_alternate_fees_{city_slug}.json",
        f"data/discovered_fees_{city_slug}.json",
        "data/discovered_alternate_fees.json",
        "data/discovered_fees.json",
        "discovered_alternate_fees.json",
        "discovered_fees.json"
    ]
    
    deleted_count = 0
    for path in files_to_delete:
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f" - Deleted intermediate file: {path}")
                deleted_count += 1
            except Exception as e:
                print(f" - Warning: Failed to delete {path}: {e}")
                
    print(f"Cleanup finished. Deleted {deleted_count} intermediate files.")
    return True

# ─────────────────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="School Data Pure-Python Scraper & Imputation Pipeline")
    parser.add_argument("--city", type=str, default="bangalore", help="Target city name (e.g. bangalore, delhi, mumbai)")
    parser.add_argument("--step", type=str, default="all", 
                        choices=["all", "discover_uniapply", "extract_uniapply", "scrape_ezyschooling_api", "geocode", "enrich_ezyschooling", "enrich_edustoke", "process", "stats", "cleanup"],
                        help="Pipeline step to execute")
    parser.add_argument("--limit", type=int, default=150, help="Maximum alternate portal queries in a single step")
    parser.add_argument("--delay-min", type=int, default=4, help="Min delay between queries (seconds)")
    parser.add_argument("--delay-max", type=int, default=8, help="Max delay between queries (seconds)")
    parser.add_argument("--force-download", action="store_true", help="Force Ezyschooling API re-download")
    
    args = parser.parse_args()
    
    city_slug, city_clean = get_city_slugs(args.city)
    
    print("=" * 60)
    print(f"  School Data Pipeline Orchestrator (Pure Python)  ")
    print(f"  Target City: {city_clean} (Slug: {city_slug})")
    print(f"  Executing Step: {args.step}")
    print("=" * 60)
    
    start_time = time.time()
    
    if args.step == "all":
        # 1A. UniApply Discover
        if not step_discover_uniapply(city_slug, city_clean):
            print("Pipeline aborted at UniApply discovery stage.")
            sys.exit(1)
            
        # 1B. UniApply Extract
        if not step_extract_uniapply(city_slug, city_clean, run_limit=args.limit):
            print("Pipeline aborted at UniApply extraction stage.")
            sys.exit(1)
            
        # 1C. API Scrape & Merge
        if not step_scrape_ezyschooling_api(city_slug, city_clean, force_download=args.force_download):
            print("Pipeline aborted at scrape/merge stage.")
            sys.exit(1)
            
        # 2. Geocode
        if not step_geocode(city_slug, city_clean):
            print("Pipeline aborted at geocode stage.")
            sys.exit(1)
            
        # 3. Enrich Ezyschooling
        step_enrich_ezyschooling(city_slug, city_clean, run_limit=args.limit, delay_min=args.delay_min, delay_max=args.delay_max)
        
        # 4. Enrich Edustoke
        step_enrich_edustoke(city_slug, city_clean, run_limit=args.limit, delay_min=args.delay_min, delay_max=args.delay_max)
        
        # 5. Process (Board Imputation and Student Counts)
        step_process(city_slug, city_clean)
        
        # 6. Report Stats
        step_stats(city_slug)
        
        # 7. Clean up intermediate files
        step_cleanup(city_slug)
        
    elif args.step == "discover_uniapply":
        step_discover_uniapply(city_slug, city_clean)
    elif args.step == "extract_uniapply":
        step_extract_uniapply(city_slug, city_clean, run_limit=args.limit)
    elif args.step == "scrape_ezyschooling_api":
        step_scrape_ezyschooling_api(city_slug, city_clean, force_download=args.force_download)
    elif args.step == "geocode":
        step_geocode(city_slug, city_clean)
    elif args.step == "enrich_ezyschooling":
        step_enrich_ezyschooling(city_slug, city_clean, run_limit=args.limit, delay_min=args.delay_min, delay_max=args.delay_max)
    elif args.step == "enrich_edustoke":
        step_enrich_edustoke(city_slug, city_clean, run_limit=args.limit, delay_min=args.delay_min, delay_max=args.delay_max)
    elif args.step == "process":
        step_process(city_slug, city_clean)
    elif args.step == "stats":
        step_stats(city_slug)
    elif args.step == "cleanup":
        step_cleanup(city_slug)
        
    duration = time.time() - start_time
    print(f"\nPipeline step '{args.step}' completed in {duration:.1f} seconds.")

if __name__ == "__main__":
    main()
