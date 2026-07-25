import threading
from datetime import datetime

class PipelineLogger:
    """
    A blisteringly fast, ultra-lightweight linear logger.
    Abandons full-screen dashboard rendering in favor of a standard, stable standard output stream.
    """
    def __init__(self, total_cities=1):
        self.lock = threading.Lock()
        
        self.city_name = "Initializing"
        self.total_cities = total_cities
        self.current_city_idx = 0
        
        self.global_saved = 0
        self.global_dupes = 0
        self.bucket_trackers = {}

    def start(self):
        print("\n" + "="*50)
        print("🚀 FLENT LENS PIPELINE ENGINE STARTED")
        print("="*50 + "\n")

    def stop(self):
        print("\n" + "="*50)
        print("✅ FLENT LENS PIPELINE FINISHED")
        print("="*50 + "\n")

    def update_city(self, city_name, phase, idx=None, total=None):
        with self.lock:
            self.city_name = city_name
            if idx is not None: self.current_city_idx = idx
            if total is not None: self.total_cities = total
            
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"\n[{timestamp}] ➔ [{phase.upper()}] {city_name} ({self.current_city_idx}/{self.total_cities})")

    def update_worker(self, w_id, w_name, status, added=0, dupes=0, delta_added=0, delta_dupes=0):
        with self.lock:
            if w_id not in self.bucket_trackers:
                self.bucket_trackers[w_id] = {"added": 0, "dupes": 0}
                
            if delta_added > 0 or delta_dupes > 0:
                self.global_saved += delta_added
                self.global_dupes += delta_dupes
                self.bucket_trackers[w_id]["added"] += delta_added
                self.bucket_trackers[w_id]["dupes"] += delta_dupes
                
                # Only log specifically when new data is added to avoid pure-dupe spamming
                if delta_added > 0:
                    time_str = datetime.now().strftime('%H:%M:%S')
                    b_add = self.bucket_trackers[w_id]["added"]
                    print(f"[{time_str}]    [+] {self.city_name} {w_name}: +{delta_added} records (Bucket Total: {b_add} | Global Total: {self.global_saved})")
                    
            # If the worker errors or warns, explicitly print it
            if "Error" in status or "Fail" in status or "blocking" in status:
                print(f"[{datetime.now().strftime('%H:%M:%S')}]    [!] {self.city_name} {w_name}: {status}")

    def log(self, message):
        with self.lock:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
