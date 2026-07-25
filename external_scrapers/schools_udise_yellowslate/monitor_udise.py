import urllib.request
import json
import time
import datetime
import sys

def get_status():
    try:
        url = "http://127.0.0.1:5050/api/status"
        req = urllib.request.urlopen(url, timeout=5)
        return json.loads(req.read())
    except Exception as e:
        return None

def print_dashboard():
    data = get_status()
    if not data or "job" not in data or not data["job"]:
        print(f"\033[H\033[J") # Clear terminal
        print("="*60)
        print("           UDISE SCRAPER PROGRESS MONITOR")
        print("="*60)
        print(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
        print("UDISE Scraper Dashboard Offline or no job currently running.")
        print("="*60)
        return

    job = data["job"]
    status = job.get("status", "unknown")
    comp_pins = job.get("completed_pincodes", 0)
    total_pins = job.get("total_pincodes", 0)
    comp_schools = job.get("completed_schools", 0)
    disc_schools = job.get("total_schools", 0)
    
    # Parse timestamps
    try:
        created = datetime.datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))
        updated = datetime.datetime.fromisoformat(job["updated_at"].replace("Z", "+00:00"))
        elapsed_sec = (updated - created).total_seconds()
    except Exception:
        elapsed_sec = 0
        
    elapsed_min = max(0.1, elapsed_sec / 60.0)
    pins_left = total_pins - comp_pins

    # Estimates
    if comp_pins > 0:
        pin_rate = comp_pins / elapsed_min
        avg_schools_per_pin = disc_schools / comp_pins
        est_total_schools = avg_schools_per_pin * total_pins
        eta_min = pins_left / pin_rate if pin_rate > 0 else 0
        eta_time = datetime.datetime.now() + datetime.timedelta(minutes=eta_min)
        eta_str = eta_time.strftime("%I:%M %p")
    else:
        pin_rate = 0
        est_total_schools = disc_schools
        eta_min = 0
        eta_str = "Calculating..."

    print(f"\033[H\033[J") # Clear terminal
    print("="*60)
    print("           UDISE SCRAPER PROGRESS MONITOR")
    print("="*60)
    print(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
    print(f"Job Status: {status.upper()}")
    print(f"Elapsed Time: {elapsed_min:.1f} minutes")
    print("-"*60)
    print(f"Pincodes Processed: {comp_pins} / {total_pins} ({comp_pins/total_pins*100:.1f}%)")
    print(f"Pincodes Remaining: {pins_left}")
    print(f"Current Pincode:    {job.get('current_pincode') or 'N/A'}")
    print("-"*60)
    print(f"Schools Completed:  {comp_schools}")
    print(f"Schools Discovered: {disc_schools}")
    print(f"Est. Total Schools: {int(est_total_schools)}")
    print("-"*60)
    print(f"Processing Speed:   {pin_rate:.2f} pincodes/min | {comp_schools/elapsed_min:.1f} schools/min")
    if eta_min > 0:
        print(f"ETA:                {eta_min:.1f} minutes (approx. {eta_str})")
    else:
        print(f"ETA:                {eta_str}")
    print("="*60)
    print("Refreshing every 2 secs. Press Ctrl+C to exit.")
    sys.stdout.flush()

if __name__ == "__main__":
    while True:
        print_dashboard()
        time.sleep(2)
