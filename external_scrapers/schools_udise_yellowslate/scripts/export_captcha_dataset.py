import json
import sqlite3
import base64
import re
from pathlib import Path
import csv

DB_PATH = Path('/Users/malleswararao/Desktop/school extraction/data/runtime/udise_data.sqlite3')
OUTPUT_DIR = Path('/Users/malleswararao/Desktop/school extraction/data/captcha_dataset')
IMAGES_DIR = OUTPUT_DIR / 'images'

def main():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Fetch solved CAPTCHA messages and extract the answers
    c.execute("""
        SELECT details_json, message 
        FROM job_events 
        WHERE event='captcha.ocr_solved'
    """)
    
    logs = c.fetchall()
    
    # Create a mapping of challenge_id -> solved text
    challenge_to_text = {}
    for details_json, message in logs:
        try:
            details = json.loads(details_json) if details_json else {}
            challenge_id = details.get('challenge_id')
            if challenge_id is None:
                continue
            # Extract captcha text from message
            match = re.search(r'solved CAPTCHA for PIN \d+: (\w+)', message)
            if match:
                captcha_text = match.group(1)
                challenge_to_text[int(challenge_id)] = captcha_text
        except Exception:
            continue
            
    # 2. Fetch the corresponding images from captcha_challenges
    c.execute("SELECT id, image_data_url FROM captcha_challenges")
    challenges = c.fetchall()
    
    exported_count = 0
    labels = []
    
    for cid, img_url in challenges:
        if cid not in challenge_to_text:
            continue
            
        captcha_label = challenge_to_text[cid]
        
        # Decode base64 image
        if img_url.startswith("data:image/png;base64,"):
            try:
                base64_data = img_url.split(",", 1)[1]
                img_bytes = base64.b64decode(base64_data)
                
                img_filename = f"captcha_{cid}.png"
                img_path = IMAGES_DIR / img_filename
                
                with open(img_path, 'wb') as img_f:
                    img_f.write(img_bytes)
                    
                labels.append({
                    'filename': f"images/{img_filename}",
                    'label': captcha_label
                })
                exported_count += 1
            except Exception as e:
                print(f"Error decoding challenge {cid}: {e}")
                
    # 3. Write labels CSV
    csv_path = OUTPUT_DIR / 'labels.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as csv_f:
        writer = csv.DictWriter(csv_f, fieldnames=['filename', 'label'])
        writer.writeheader()
        writer.writerows(labels)
        
    print(f"Dataset generation complete!")
    print(f"Exported {exported_count} CAPTCHAs to {OUTPUT_DIR}")
    print(f"Labels written to {csv_path}")
    
    conn.close()

if __name__ == "__main__":
    main()
