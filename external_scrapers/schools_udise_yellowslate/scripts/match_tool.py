import os
import json
import re
from difflib import SequenceMatcher
from flask import Flask, jsonify, request, render_template

app = Flask(__name__, template_folder='templates', static_folder='static')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data', 'output')

# Paths
YS_UNMATCHED_PATH = os.path.join(DATA_DIR, 'unmatched_yellowslate.json')
UDISE_COMPACT_PATH = os.path.join(DATA_DIR, 'schools_analysis_bangalore_compact.json')
AUTO_MATCHED_PATH = os.path.join(DATA_DIR, 'auto_matched_schools.json')
MANUAL_MATCHED_PATH = os.path.join(DATA_DIR, 'manual_matched_schools.json')
SKIPPED_PATH = os.path.join(DATA_DIR, 'skipped_yellowslate.json')

# In-memory stores
ys_unmatched = []
udise_schools = []
matched_udise_ids = set()
skipped_ys_names = set()
unique_pincodes = []

def similar(a, b):
    if not a or not b:
        return 0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def normalize_name(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'\b(school|public|convent|english|kannada|urdu|high|higher|primary|nursery|vidya|kendra|institution|academy|international|early|learning|centre|center|pre|preschool|montessori|play|playgroup|kindergarten|bengaluru|bangalore)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name

def load_data():
    global ys_unmatched, udise_schools, matched_udise_ids, skipped_ys_names, unique_pincodes
    
    # Load unmatched Yellowslate schools
    if os.path.exists(YS_UNMATCHED_PATH):
        with open(YS_UNMATCHED_PATH, 'r') as f:
            ys_unmatched = json.load(f)
            
        # Sort unmatched by highest fee bracket first
        def get_fee_min(y):
            fee = y.get('fee') or {}
            return fee.get('search_bracket_min') or 0
        ys_unmatched.sort(key=get_fee_min, reverse=True)
            
    # Load UDISE schools
    if os.path.exists(UDISE_COMPACT_PATH):
        with open(UDISE_COMPACT_PATH, 'r') as f:
            data = json.load(f)
            udise_schools = data.get('schools', [])
            for u in udise_schools:
                u['norm_name'] = normalize_name(u['metadata']['school_name'])
                u['pincode_str'] = str(u['metadata'].get('pincode', '')).strip()
            
            # Extract unique pincodes
            unique_pincodes = sorted(list(set(u['pincode_str'] for u in udise_schools if u['pincode_str'])))
                
    # Load auto matched and manual matched to exclude them
    if os.path.exists(AUTO_MATCHED_PATH):
        with open(AUTO_MATCHED_PATH, 'r') as f:
            auto_matches = json.load(f)
            for m in auto_matches:
                matched_udise_ids.add(m['udise']['udise_code'])
                
    if os.path.exists(MANUAL_MATCHED_PATH):
        with open(MANUAL_MATCHED_PATH, 'r') as f:
            manual_matches = json.load(f)
            for m in manual_matches:
                matched_udise_ids.add(m['udise_code'])
                
    # Load skipped
    if os.path.exists(SKIPPED_PATH):
        with open(SKIPPED_PATH, 'r') as f:
            skipped_ys_names = set(json.load(f))
            
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/next')
def next_unmatched():
    # Find the next Yellowslate school that hasn't been matched or skipped
    manual_matched_ys = set()
    if os.path.exists(MANUAL_MATCHED_PATH):
        with open(MANUAL_MATCHED_PATH, 'r') as f:
            matches = json.load(f)
            manual_matched_ys = set([m['yellowslate_name'] for m in matches])
            
    target_ys = None
    for y in ys_unmatched:
        name = y.get('school_name', '')
        if name not in manual_matched_ys and name not in skipped_ys_names:
            target_ys = y
            break
            
    if not target_ys:
        return jsonify({"status": "done", "message": "No more unmatched schools!"})
        
    y_name = target_ys.get('school_name', '')
    y_norm_name = normalize_name(y_name)
    y_pincode = str(target_ys.get('school_location', {}).get('pincode', '')).strip()
    y_area = (target_ys.get('area') or "").lower()
    
    # Calculate scores
    candidates = []
    for u in udise_schools:
        if u['udise_code'] in matched_udise_ids:
            continue
            
        score = similar(y_norm_name, u['norm_name'])
        if y_pincode and u['pincode_str'] and y_pincode == u['pincode_str']:
            score += 0.2
            
        u_address = (u['metadata'].get('address') or "").lower()
        if y_area and len(y_area) > 3 and y_area in u_address:
            score += 0.1
            
        candidates.append((score, u))
        
    # Sort and take top 5
    candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = []
    for score, u in candidates[:5]:
        top_candidates.append({
            "udise_code": u['udise_code'],
            "name": u['metadata']['school_name'],
            "address": u['metadata'].get('address', ''),
            "pincode": u['metadata'].get('pincode', ''),
            "board": u['metadata'].get('board_affiliation', {}).get('secondary', ''),
            "enrollment": u.get('enrollment', {}).get('all', {}).get('total', 0),
            "score": round(score, 2)
        })
        
    return jsonify({
        "status": "ok",
        "yellowslate": target_ys,
        "candidates": top_candidates
    })

@app.route('/api/match', methods=['POST'])
def match_school():
    data = request.json
    ys_name = data.get('yellowslate_name')
    udise_code = data.get('udise_code')
    ys_data = data.get('yellowslate_data')
    
    if not ys_name or not udise_code:
        return jsonify({"error": "Missing data"}), 400
        
    # Add to manual_matched
    matches = []
    if os.path.exists(MANUAL_MATCHED_PATH):
        with open(MANUAL_MATCHED_PATH, 'r') as f:
            matches = json.load(f)
            
    matches.append({
        "yellowslate_name": ys_name,
        "udise_code": udise_code,
        "yellowslate_data": ys_data
    })
    
    with open(MANUAL_MATCHED_PATH, 'w') as f:
        json.dump(matches, f, indent=2)
        
    matched_udise_ids.add(udise_code)
    return jsonify({"status": "ok"})

@app.route('/api/skip', methods=['POST'])
def skip_school():
    data = request.json
    ys_name = data.get('yellowslate_name')
    
    if not ys_name:
        return jsonify({"error": "Missing data"}), 400
        
    skipped_ys_names.add(ys_name)
    with open(SKIPPED_PATH, 'w') as f:
        json.dump(list(skipped_ys_names), f, indent=2)
        
    return jsonify({"status": "ok"})

@app.route('/api/unmatch', methods=['POST'])
def unmatch_school():
    data = request.json
    udise_code = data.get('udise_code')
    if not udise_code:
        return jsonify({"error": "Missing udise_code"}), 400
        
    removed = False
    
    # 1. Remove from manual matches
    if os.path.exists(MANUAL_MATCHED_PATH):
        with open(MANUAL_MATCHED_PATH, 'r') as f:
            manual_matches = json.load(f)
        new_manual = [m for m in manual_matches if m.get('udise_code') != udise_code]
        if len(new_manual) < len(manual_matches):
            with open(MANUAL_MATCHED_PATH, 'w') as f:
                json.dump(new_manual, f, indent=2)
            removed = True
            
    # 2. Remove from auto matches
    if os.path.exists(AUTO_MATCHED_PATH):
        with open(AUTO_MATCHED_PATH, 'r') as f:
            auto_matches = json.load(f)
        new_auto = [m for m in auto_matches if m.get('udise', {}).get('udise_code') != udise_code]
        if len(new_auto) < len(auto_matches):
            with open(AUTO_MATCHED_PATH, 'w') as f:
                json.dump(new_auto, f, indent=2)
            removed = True
            
    if removed:
        global matched_udise_ids
        if udise_code in matched_udise_ids:
            matched_udise_ids.remove(udise_code)
        load_data()
        return jsonify({"status": "ok"})
        
    return jsonify({"error": "Match not found"}), 404

@app.route('/api/search_udise')
def search_udise():
    query = request.args.get('q', '').strip()
    target_name = request.args.get('target_name', '').strip()
    
    if not query:
        return jsonify([])
        
    query_norm = normalize_name(query)
    target_norm = normalize_name(target_name) if target_name else ""
    
    candidates = []
    for u in udise_schools:
        if u['udise_code'] in matched_udise_ids:
            continue
            
        u_name = u['metadata']['school_name']
        u_code = u['udise_code']
        u_pincode = u['pincode_str']
        
        match = False
        if query.lower() in u_name.lower():
            match = True
        elif query in u_code:
            match = True
        elif query in u_pincode:
            match = True
        elif query_norm and query_norm in u['norm_name']:
            match = True
            
        if match:
            if target_norm:
                score = similar(target_norm, u['norm_name'])
            else:
                score = similar(query_norm, u['norm_name']) if query_norm else 0.5
                
            candidates.append((score, u))
            
    candidates.sort(key=lambda x: x[0], reverse=True)
    
    results = []
    for score, u in candidates[:20]:
        results.append({
            "udise_code": u['udise_code'],
            "name": u['metadata']['school_name'],
            "address": u['metadata'].get('address', ''),
            "pincode": u['metadata'].get('pincode', ''),
            "board": u['metadata'].get('board_affiliation', {}).get('secondary', ''),
            "enrollment": u.get('enrollment', {}).get('all', {}).get('total', 0),
            "score": round(score, 2)
        })
        
    return jsonify(results)

@app.route('/api/pincodes')
def get_pincodes():
    return jsonify(unique_pincodes)

@app.route('/api/udise_list')
def get_udise_list():
    pincode = request.args.get('pincode', '').strip()
    search = request.args.get('search', '').strip().lower()
    status_filter = request.args.get('status', 'all').strip().lower()
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    
    matches_map = {}
    if os.path.exists(AUTO_MATCHED_PATH):
        with open(AUTO_MATCHED_PATH, 'r') as f:
            auto_matches = json.load(f)
            for m in auto_matches:
                ud_code = m.get('udise', {}).get('udise_code')
                ys_school = m.get('yellowslate', {})
                if ud_code:
                    matches_map[ud_code] = {
                        "school_name": ys_school.get('school_name', 'N/A'),
                        "url": ys_school.get('school_url', ''),
                        "match_type": "auto"
                    }
                    
    if os.path.exists(MANUAL_MATCHED_PATH):
        with open(MANUAL_MATCHED_PATH, 'r') as f:
            manual_matches = json.load(f)
            for m in manual_matches:
                ud_code = m.get('udise_code')
                ys_name = m.get('yellowslate_name', 'N/A')
                ys_data = m.get('yellowslate_data') or {}
                if ud_code:
                    matches_map[ud_code] = {
                        "school_name": ys_name,
                        "url": ys_data.get('school_url', '') if isinstance(ys_data, dict) else '',
                        "match_type": "manual"
                    }
                    
    filtered = []
    for u in udise_schools:
        u_pincode = u['pincode_str']
        if pincode and pincode != u_pincode:
            continue
            
        u_name = u['metadata']['school_name']
        u_code = u['udise_code']
        if search and (search not in u_name.lower() and search not in u_code):
            continue
            
        is_matched = u_code in matches_map
        if status_filter == 'matched' and not is_matched:
            continue
        if status_filter == 'unmatched' and is_matched:
            continue
            
        matched_info = matches_map.get(u_code)
        filtered.append({
            "udise_code": u_code,
            "school_name": u_name,
            "pincode": u_pincode,
            "address": u['metadata'].get('address', ''),
            "is_matched": is_matched,
            "matched_to": matched_info['school_name'] if matched_info else None,
            "matched_to_url": matched_info['url'] if matched_info else None,
            "match_type": matched_info['match_type'] if matched_info else None
        })
        
    total = len(filtered)
    start = (page - 1) * limit
    end = start + limit
    paginated = filtered[start:end]
    
    return jsonify({
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "schools": paginated
    })

@app.route('/udise')
def udise_page():
    return render_template('udise.html')


if __name__ == '__main__':
    load_data()
    app.run(debug=True, port=8000)
