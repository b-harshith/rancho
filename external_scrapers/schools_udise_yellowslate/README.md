# UDISE+ human-assisted network collector

This local Python application opens UDISE+ in Chrome, submits PIN-code searches,
waits for a human to enter each CAPTCHA, and saves complete JSON API responses to
SQLite. School data is captured from network responses rather than scraped from
HTML.

After human CAPTCHA entry, the search is issued directly from the active Chrome
session to `search-schools`; this avoids fragile Angular form-model automation
while retaining the site's cookies, CAPTCHA session, and full network capture.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open <http://127.0.0.1:5050>, choose an optional PIN limit, and start the job.
The dashboard displays each CAPTCHA and pauses until you submit it.

Set `UDISE_HEADLESS=0` to run Chrome visibly. Other optional variables are
`UDISE_DB`, `UDISE_PINCODES`, `UDISE_CHROME`, and `PORT`. Browser concurrency
defaults to 10 and can be lowered with `UDISE_BROWSER_CONCURRENCY`. Concurrent
five-school API batches default to 2 and can be adjusted with
`UDISE_REPORT_BATCH_CONCURRENCY`.

## Storage

The default database is `data/runtime/udise_data.sqlite3`. It contains job and PIN progress,
normalized school summaries, CAPTCHA workflow metadata (never the answer), and
all browser request metadata in `network_requests`. Full relevant API response
metadata and JSON bodies are stored in `network_responses`.

Structured step-by-step diagnostics are stored in `job_events`, displayed in the
dashboard, and also written to the rotating `logs/udise_scraper.log` file.

## Project layout

```text
app.py                  Local dashboard entry point
udise_scraper/          Browser, database, worker, and pool modules
templates/              Dashboard HTML
static/                 Dashboard JavaScript and CSS
scripts/                Extraction and analysis utilities
data/input/             KML and PIN-code inputs
data/output/            Nested JSON and analysis report
data/runtime/           SQLite collection database
logs/                   Rotating runtime logs
```

Regenerate analytical outputs from the project root:

```bash
.venv/bin/python scripts/export_analysis_json.py
.venv/bin/python scripts/generate_analysis_report.py
.venv/bin/python scripts/match_school_fees.py
```

The search response already contains every school for a PIN. The site's visible
10/25/50/100 pagination is client-side, so the collector does not need to click
through result pages. For every school it opens the reliably deep-linkable
**Know More** route, captures that page's APIs, then requests the report-card API
fan-out directly from the same browser session. It does not depend on opening the
Angular Report Card action in a new page.

Use the dashboard's **Export JSON** link to export all stored data for a job.
