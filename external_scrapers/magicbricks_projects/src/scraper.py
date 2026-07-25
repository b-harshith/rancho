import json
import os
import re
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    from curl_cffi import requests as cf_requests
except ImportError:
    raise ImportError("[ERROR] Missing curl_cffi: Please run `pip install curl_cffi`")

class MagicbricksScraper:
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        
        self.STATE_REGEX = re.compile(r"window\.SERVER_PRELOADED_STATE_\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL)
        self.ID_REGEX = re.compile(r'"encId":\s*"([^"]+)"')
        
        # Matches the Magicbricks commercial search URL provided for Noida.
        self.base_url = (
            "https://www.magicbricks.com/property-for-rent/commercial-real-estate"
            "?bedroom=&proptype={property_types}&cityName={city}"
        )

    def load_seen_ids(self, filename: str):
        seen = set()
        if not os.path.exists(filename): return seen
        with open(filename, "r", encoding="utf-8") as f:
            ids = self.ID_REGEX.findall(f.read())
            seen.update(ids)
        return seen

    def fetch_page(self, url: str, session) -> str:
        """Returns HTML on success, '404' on 404 response, None on error."""
        try:
            resp = session.get(url, impersonate="chrome", timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if "404" in str(e): return "404"
            return None

    def extract_json(self, html: str) -> dict:
        match = self.STATE_REGEX.search(html)
        if not match: return None
        try: return json.loads(match.group(1))
        except: return None

    def scrape_city(self, city_name: str):
        safe_city = getattr(self.config, "OUTPUT_SLUG", city_name.lower().replace(" ", "_").replace("/", "_"))
        out_file = os.path.join(self.config.PATHS["raw_dir"], f"{safe_city}.jsonl")
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        
        seen_ids = self.load_seen_ids(out_file)
        self.logger.log(f"[Scraper] Found {len(seen_ids):,} existing records for {city_name}.")
        
        lock_ids = threading.Lock()
        lock_file = threading.Lock()
        
        categories = getattr(self.config, "CATEGORIES", {})
        if not categories:
            # Fallback to legacy configuration formats
            categories = {
                "commercial_rent": {
                    "url_template": "https://www.magicbricks.com/property-for-rent/commercial-real-estate?bedroom=&proptype={property_types}&cityName={city}",
                    "property_types": getattr(self.config, "COMMERCIAL_PROPTYPES", []),
                    "price_buckets": getattr(self.config, "PRICE_BUCKETS", [])
                }
            }

        city_param = city_name.replace(" ", "-")

        for cat_name, cat_config in categories.items():
            self.logger.log(f"[Scraper] Starting category '{cat_name}' for {city_name}...")
            
            url_template = cat_config["url_template"]
            prop_types_list = cat_config["property_types"]
            property_types = ",".join(prop_types_list)
            all_buckets = cat_config["price_buckets"]
            
            def bucket_worker(bucket_info):
                b_min, b_max = bucket_info
                w_id = threading.get_ident() % 10000
                
                # Format worker name to be readable
                if b_max >= 99999999:
                    limit_str = "+"
                else:
                    limit_str = f"-{b_max//1000}k" if b_max < 100000 else f"-{b_max//100000}L"
                    if b_max >= 10000000:
                        limit_str = f"-{b_max//10000000}Cr"
                
                if b_min < 100000:
                    start_str = f"{b_min//1000}k"
                elif b_min < 10000000:
                    start_str = f"{b_min//100000}L"
                else:
                    start_str = f"{b_min//10000000}Cr"
                    
                w_name = f"[{cat_name}|{start_str}{limit_str}]"
                
                session = cf_requests.Session()
                self.logger.update_worker(w_id, w_name, "Booting", 0, 0)
                
                nonlocal seen_ids
                
                try:
                    for page in range(1, self.config.SCRAPER_SETTINGS['page_limit'] + 1):
                        url = (
                            f"{url_template.format(property_types=property_types, city=city_param)}"
                            f"&BudgetMin={b_min}&BudgetMax={b_max}"
                        )
                        if page > 1: url += f"&page={page}"
                        
                        html = None
                        for attempt in range(3):
                            html = self.fetch_page(url, session)
                            if html == "404": break
                            if html: break
                            self.logger.update_worker(w_id, w_name, f"Retry ({attempt+1}/3)")
                            time.sleep((2 ** attempt) + random.uniform(1, 3))
                        
                        if html == "404":
                            self.logger.update_worker(w_id, w_name, "End (404)")
                            break
                            
                        if not html:
                            continue # Skip page on total failure

                        data = self.extract_json(html)
                        if not data: 
                            self.logger.log(f"[{city_name}/{w_name}] No JSON data found on page {page}. Portal blocking or invalid city.")
                            break

                        properties = data.get("searchResult", [])
                        if not properties:
                            break # No properties returned

                        new_items = []
                        page_dupes = 0
                        
                        with lock_ids:
                            for prop in properties:
                                pid = prop.get("encId")
                                if pid:
                                    if pid not in seen_ids:
                                        seen_ids.add(pid)
                                        prop["scraped_category"] = cat_name
                                        new_items.append(prop)
                                    else:
                                        page_dupes += 1
                        
                        if new_items:
                            with lock_file:
                                with open(out_file, "a", encoding="utf-8") as f:
                                    data["searchResult"] = new_items
                                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
                                    
                            self.logger.update_worker(w_id, w_name, f"Page {page}", delta_added=len(new_items), delta_dupes=page_dupes)
                        else:
                            self.logger.update_worker(w_id, w_name, f"Page {page} (Dupes)", delta_added=0, delta_dupes=page_dupes)
                            # Stop if we're hitting only dupes deep into the search
                            if page > 5 and page_dupes >= len(properties):
                                break 

                        if len(properties) < 20: 
                            break # MB returns 30 per page usually, less than 20 means last page.
                        
                        time.sleep(random.uniform(self.config.SCRAPER_SETTINGS['min_sleep'], self.config.SCRAPER_SETTINGS['max_sleep']))
                
                except Exception as e:
                    self.logger.log(f"Worker Error {w_name}: {str(e)}")
                finally:
                    self.logger.update_worker(w_id, w_name, "Done")

            # Execute parallel workers
            with ThreadPoolExecutor(max_workers=self.config.SCRAPER_SETTINGS['max_workers']) as executor:
                for b_info in all_buckets:
                    executor.submit(bucket_worker, b_info)
            
            self.logger.log(f"[Scraper] Completed category '{cat_name}' for {city_name}.")
            
        self.logger.log(f"[Scraper] Completed {city_name} across all categories.")
