# Unified School Data Scraper & Enrichment Pipeline

A production-grade, city-parameterized web scraper and data enrichment pipeline. It extracts school profiles from UniApply (listings, facilities, geolocations, and grade-wise fees), deduplicates and calculates averages, geocodes addresses via OpenStreetMap Nominatim, and resolves missing fees using alternate portals (Ezyschooling & Edustoke).

---

## Workspace Directory Structure

The project has been unified into a parameterized, clean structure:

```
├── data/
│   ├── uniapply_bangalore.db            # SQLite database for Bangalore
│   ├── geocoding_cache_bangalore.json   # Nominatim cache for Bangalore (evades API rate limits)
│   ├── discovered_fees_bangalore.json   # Edustoke alternate fees for Bangalore
│   └── discovered_alternate_fees_bangalore.json # Ezyschooling alternate fees for Bangalore
├── diagnostics/
│   ├── check_db.py                      # Sanity checks database tables and row counts
│   ├── verify_geocoding.py              # Validates geocoding results and fee overrides
│   ├── compare_datasets.py              # Compares scraped admissions data against GIS boundary data
│   └── monitor_progress.js              # Watchdog script to monitor and self-heal scraping runs
├── logs/
│   └── scraper.log                      # Persistent scraper logs
├── src/
│   ├── config.js                        # Playwright/Node config (detects process.env.CITY)
│   ├── main.js                          # Node.js scraper CLI entry point
│   ├── scraper/
│   │   ├── discovery.js                 # School listing discovery
│   │   └── extractor.js                 # Deep details & fees crawler
│   ├── parser/
│   │   └── exporter.js                  # Normalizes SQLite data to raw JSON
│   └── utils/
│       ├── browser.js                   # Playwright browser launchers and jitters
│       ├── db.js                        # SQLite connection helpers & schema builders
│       ├── fee-parser.js                # HTML parser for UniApply fee structures
│       ├── logger.js                    # Winston console + file logger
│       └── tor.js                       # Tor proxy rotation helpers
├── package.json                         # Node dependency manifest
├── run_pipeline.py                      # Unified end-to-end Python pipeline runner
├── school_averages_summary_bangalore.json  # Final output summaries (Bangalore-specific)
├── school_averages_summary_bangalore.csv
├── school_averages_summary.json         # Generic summaries (pointing to the last run city)
├── school_averages_summary.csv
└── README.md                            # Documentation
```

---

## Setup & Installation

### 1. Node.js Scraper Setup
Install npm dependencies:
```bash
npm install
```

Ensure Playwright browser binaries are installed:
```bash
npx playwright install chromium
```

### 2. Python Post-Processing Setup
Ensure Python 3 is installed. The geocoding and alternate scrapers require `requests`, `BeautifulSoup` (bs4), and optionally `curl_cffi` (for bypass-impersonated requests to alternate portals):
```bash
pip install requests beautifulsoup4 curl_cffi
```

---

## How to Run the Unified Pipeline

The main entry point is `run_pipeline.py`. It takes a target `--city` argument and handles all scraping, calculations, and enrichments end-to-end.

### 1. Execute End-to-End (`all` step)
Sequentially runs: UniApply scraping -> deduplication -> averages calculation -> geocoding -> alternate fee resolution (Ezyschooling & Edustoke) -> final stats report.
```bash
python3 run_pipeline.py --city bangalore --step all
```
*To run for another city (e.g. Delhi, Mumbai), simply swap the city parameter:*
```bash
python3 run_pipeline.py --city delhi --step all
```

### 2. Run Individual Steps
If you want to run specific stages of the pipeline independently, use the `--step` flag:

* **Scrape only** (runs UniApply discovery, extraction, and raw JSON export):
  ```bash
  python3 run_pipeline.py --city bangalore --step scrape
  ```
* **Process only** (runs SQLite deduplication and initial JSON/CSV summary calculations, resolving alternate fees from existing cache JSONs):
  ```bash
  python3 run_pipeline.py --city bangalore --step process
  ```
* **Geocode only** (runs OSM Nominatim reverse and forward geocoding using caching):
  ```bash
  python3 run_pipeline.py --city bangalore --step geocode
  ```
* **Enrich CBSE/ICSE Fees** (scrapes missing CBSE/ICSE fees from Ezyschooling):
  ```bash
  python3 run_pipeline.py --city bangalore --step enrich_ezyschooling --limit 50
  ```
* **Enrich Remaining Fees** (scrapes missing fees from Edustoke):
  ```bash
  python3 run_pipeline.py --city bangalore --step enrich_edustoke --limit 50
  ```
* **Stats only** (prints board-wise counts, fee distributions, and student stats):
  ```bash
  python3 run_pipeline.py --city bangalore --step stats
  ```

---

## Diagnostics & Validation

The `diagnostics/` folder contains scripts for quality control and verification:

1. **Verify Geocoding & Fee Overrides**:
   Validates coordinates, postcodes, addresses, and ensures that manual fee overrides (e.g., BNM, Arrow Kids) remain intact.
   ```bash
   python3 diagnostics/verify_geocoding.py --city bangalore
   ```

2. **Verify Database Stats**:
   Inspected SQLite database tables, row counts, and sample entries:
   ```bash
   python3 diagnostics/check_db.py --city bangalore
   ```

3. **Compare with GIS boundary data**:
   Compares scraped admissions data against `unique_schools_details.csv` to report match overlap:
   ```bash
   python3 diagnostics/compare_datasets.py
   ```

4. **Watchdog Scraper Monitor**:
   Monitors active scraper logs, restarts hung worker tabs, and writes progress reports to `./logs/progress_report.md`:
   ```bash
   node diagnostics/monitor_progress.js
   ```
