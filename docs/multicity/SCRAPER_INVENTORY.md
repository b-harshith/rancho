# Scraper inventory and source-access policy

Inventory performed 2026-06-30 (Asia/Kolkata), read-only, from the paths named in `MULTI_CITY_RESEARCH_EXECUTION_PROMPT.md` plus filename-based discovery under `/Users/malleswararao/Desktop`. No production scrape or CAPTCHA interaction was performed. Timestamps are filesystem modification times and do not prove provenance. SHA-256 values identify the inspected snapshots. Secrets are intentionally not reproduced.

## Adoption decision

| Source | Authoritative starting point | Decision |
|---|---|---|
| YellowSlate | `/Users/malleswararao/Desktop/school extraction/scripts/scrape_yellowslate_fees.py` plus `scrape_yellowslate_browser.py` and `scrape_yellowslate_locations.py` | Best feature-complete school chain found, but Bangalore-specific city object/page totals/output paths must be removed before another-city use. Browser variant is the fallback when direct RSC requests fail. |
| UDISE+ | `/Users/malleswararao/Desktop/school extraction` application/database/CDP architecture, **excluding the current automatic CAPTCHA path** | The resumable SQLite/network-capture design is authoritative. Current `worker.py` is not compliant because it imports/uses EasyOCR to solve CAPTCHAs. Disable/remove that path and restore exclusively human submission before any collection. |
| MagicBricks Projects | `/Users/malleswararao/Desktop/Harshith files/final try/scrape_magicbricks_projects.py` | Only current Projects-card collector found and validated against a local Bangalore fixture. It is a starting point, not multi-city ready: city ID 3327, output path, page limit and 8 workers are hardcoded. |
| 99acres Localities | `/Users/malleswararao/Desktop/BangaloreRancho/city_rerun_bundle/scripts/source/locality/scrape_99acres_localities.py` | Newer and partly parameterized compared with the `Harshith files` copy. **Quarantined until embedded cookies are deleted/rotated and empty-by-default environment/session input is enforced.** A JavaScript fallback request still hardcodes `20_LOCATION`. |
| Practo Hospitals | `/Users/malleswararao/Desktop/BangaloreRancho/city_rerun_bundle/scripts/source/hospitals/practo_hospitals_scraper.py` | Newer, city-slug parameterized derivative of the scratch script. Starting point only; it waits on an Akamai challenge and must stop/report if challenged, never imply an automated bypass. Add sample limit, address/city validation, resumability and configurable output root. |

No Git repository was present at the supplied workspace root during this inspection (`git status` returned “not a git repository”), so Git history could not be used to establish authority. Selection is based on mtime, parameterization, fixture compatibility and feature completeness.

## Detailed inventory

### YellowSlate

| File | Modified / SHA-256 | Inputs and outputs | Dependencies | Hardcodes and operational requirements |
|---|---|---|---|---|
| `.../scripts/scrape_yellowslate_fees.py` | 2026-06-23 11:30:19 +0530 / `f65cc976...59c4` | Fetches `/search` or `/schools/{slug}` RSC payloads; writes fee schools, raw records, report, optional raw pages under `data/output/yellowslate` | Python stdlib HTTP, threads | Default city object: ID 13, Bengaluru, coordinates 12.9715987/77.5945627, slug `bengaluru`; six Bangalore-derived fee page totals; default 8 workers and transient `_rsc` value. Non-Bengaluru `--city-slug` changes only the slug and leaves the rest of the city object invalid/null-like. |
| `.../scripts/scrape_yellowslate_browser.py` | 2026-06-23 11:49:03 +0530 / `a136c8c9...d29` | Opens browser, initializes `/schools/bengaluru`, captures cards/fee data into YellowSlate output directory | Playwright + Chromium | Initialization route is fixed to Bengaluru; requires browser runtime/session cookies created by the site. No personal credential found in inspected source. |
| `.../scripts/scrape_yellowslate_locations.py` | 2026-06-23 12:04:08 +0530 / `8521e265...255` | Reads highest-bracket school JSON; fetches school profile URLs; emits locations/report | stdlib HTTP, threads | Consumes Bangalore-named/upstream outputs. It is enrichment, not city discovery. |

Local fixture evidence: `yellowslate_schools_with_locations.json` has 2,213 records; the inspected first record links to `/school/bengaluru/...`. This supports only the Bangalore/Bengaluru mapping, not any other city.

### UDISE+

| Component | Modified / SHA-256 | Inputs and outputs | Dependencies | Requirements / risks |
|---|---|---|---|---|
| `app.py`, `udise_scraper/{cdp,database,pool,worker}.py` | `worker.py`: 2026-06-30 09:48:44 +0530 / `0498fd42...aea` | PIN list JSON -> Chrome/CDP requests -> resumable SQLite (`jobs`, PIN tasks, school summaries, request/response evidence), job JSON export | Flask, requests, websocket-client, Chrome; current requirements also contain EasyOCR | PIN-based rather than city-ID based. Runtime needs local Chrome and a live UDISE session. Current source calls `_solve_captcha` and EasyOCR before submission; this violates the explicit no-automated-CAPTCHA rule. README still says human-assisted and is stale relative to code. The worker also logs the OCR answer in an event message; do not run this mode. |

Authority rationale: the database/checkpoint/network-evidence architecture is substantially more complete than standalone extraction scripts. Adoption is conditional on a code review proving the OCR branch and answer logging are disabled and dashboard-only human entry is the sole path. CAPTCHA images/answers are sensitive ephemeral workflow data and must not be committed.

### MagicBricks Projects

`scrape_magicbricks_projects.py` was modified 2026-06-26 13:52:10 +0530, SHA-256 `6dd58ed0...0e7`. It calls `mbproject/newProjectCards`, filters project fields, appends JSONL, resumes by `psmid`, retries three times with exponential delay/jitter, and stops on empty/duplicate pages. Dependency: `curl_cffi`. No login secret was found.

Hardcodes: `CITY_ID=3327` (Bangalore), `data/raw/bangalore_projects.jsonl`, page ceiling 1500, eight workers, fixed 30-second timeout and fixed Chrome impersonation. Parallel page allocation can overshoot the first empty page and eight workers is not demonstrably conservative. The local fixture has 26,108 lines; its first record has `ctname: Bangalore`, a Bangalore PDP URL and PIN 560076. That is valid regression evidence for city ID 3327 only. Every new city ID must be observed from MagicBricks itself and a one-page response must pass `ctname`/address validation.

### 99acres Localities

The original `Harshith files/final try/scrape_99acres_localities.py` (2026-06-10 14:37:04 +0530, `72affb0c...f606`) is Bangalore-only and embeds a raw personal/session cookie string. The rerun-bundle derivative (2026-06-13 16:02:56 +0530, `979c4ff3...c425`) adds `CITY_SLUG`, `API_CITY_ID` and `COOKIE_HEADER` environment inputs and city-named output, but retains the embedded cookie string as a default, a Bangalore target URL, and a fallback browser `fetch` with `cityId=20_LOCATION`. Both are unsafe to execute or commit unchanged. Treat all exposed cookie values as compromised and rotate/revoke them outside this repository.

Dependencies: Playwright/Chromium and `curl_cffi`; a valid user-authorized browser session; fresh request-scoped API and authorization tokens. Outputs are append JSONL pages. The original truncates output at startup, so it is not resume-safe.

Local fixture evidence: 54 JSONL page envelopes. Sample records consistently report `cityName: Bangalore`, `cityPageUrl: /bangalore-reviews-and-ratings-wrffid`; the request configuration uses `20_LOCATION`. Note that nested `srpCriteria.city` values vary across records, so they must not be mistaken for the city-page API ID.

### Practo Hospitals

The scratch script (2026-06-12 15:22:55 +0530, `a4237faf...89365`) hardcodes `city=bangalore` and Bangalore output names. The rerun-bundle copy (2026-06-13 15:41:26 +0530, `c6b18243...a22b`) adds environment `CITY_SLUG` and city-derived JSON/JSONL filenames; otherwise the algorithms are equivalent. Both use Playwright/Chromium, parse `window.__REDUX_STATE__`, deduplicate by hospital ID, sleep three seconds per page and overwrite final outputs.

No login secret is present. The script detects an Akamai challenge title and waits up to 30 seconds; compliant behavior must stop and request lawful human intervention/abandon the run if it persists. Waiting is not evidence that a challenge was lawfully solved. Local fixture `first_hospital.json` reports `city: Bangalore`, `/bangalore/...` URLs and an Indiranagar address, supporting only slug `bangalore`.

## Required preflight before production collection

1. Obtain documented owner approval for collection and check the source's then-current terms, robots directives and API/access-control boundaries. This inventory is technical evidence, not legal advice.
2. Never bypass CAPTCHA, challenge pages, authentication or rate limiting. UDISE must be human-assisted only; Practo/other anti-bot challenges are a stop condition unless the site offers an authorized path.
3. Remove embedded 99acres cookies from every adopted copy and history; rotate them. Runtime session material must be supplied from ignored local storage/environment, be empty by default, redacted in logs, and never written to manifests/raw payloads.
4. Discover each city through the site's own selector/rendered state/network request. Do not mutate Bangalore IDs/slugs by analogy. Preserve `source_city_id` and `source_city_name`, especially for Delhi NCR components.
5. Run one page/sample only. Require at least 90% of sampled records to match the expected city/region using returned city labels plus address/PIN/bounds; fail on repeated Bangalore fixture IDs/names for another city.
6. Default to one worker and conservative delay; honor `Retry-After`; use bounded exponential backoff+jitter, request timeout, response cache and checkpoints. Escalate concurrency only after written evidence it is allowed and harmless.
7. Save request URL with query values but redact cookies, authorization/API tokens, CAPTCHA values and personal identifiers. Hash raw payloads and retain timestamps/version for audit.

## Unknowns blocking seven-city mappings

Exact YellowSlate city objects/page counts, MagicBricks numeric IDs, 99acres API IDs/review URLs/session city values, Practo canonical slugs, and UDISE in-scope PIN sets for Delhi NCR, Mumbai, Hyderabad, Chennai, Kolkata, Pune and Ahmedabad were not verified from local evidence. Network/source-selector inspection was not performed in this bounded inventory. They remain explicitly `unknown`; no guessed registry values should be admitted.
