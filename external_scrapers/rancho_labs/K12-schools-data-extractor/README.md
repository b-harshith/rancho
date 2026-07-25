# K12 Schools Data Extractor

An asynchronous CLI tool that autonomously scrapes school board registries (CBSE, ICSE, IB), performs dual-pronged deep-crawling for compliance **AND** fee documents, extracts unstructured text (including from Google Drive/Sheets), and uses an LLM to generate a clean, structured master database of school infrastructure, volume, and pricing data.

## Architecture

```
Seed Generator → Deep Crawler → Text Extractor → LLM Engine → Validator → Exporter
  (Module 1)      (Module 2)     (Module 3)       (Module 4)   (Module 5)  (Module 6)
```

Each module is idempotent — if the pipeline crashes at school N, restart picks up at N+1 via SQLite state tracking.

## Quick Start

### Prerequisites

- Python 3.11+
- macOS with Homebrew
- Tesseract OCR: `brew install tesseract`
- OpenAI API key

### Setup

```bash
cd K12-schools-data-extractor

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env with your OPENAI_API_KEY
```

### Usage

```bash
# Full pipeline for a city
python main.py run --city bangalore

# Force re-scrape seed lists
python main.py run --city bangalore --force-seed

# Debug a single school URL
python main.py debug-url https://school.com/disclosure

# Check pipeline status
python main.py status

# Clean all data and reset
python main.py clean --yes
```

## Project Structure

```
K12-schools-data-extractor/
├── main.py                        # CLI entry point (Typer)
├── pyproject.toml                 # Dependencies & project config
├── .env.example                   # Environment template
│
├── config/
│   └── settings.py                # All constants & config (single source of truth)
│
├── src/
│   ├── models.py                  # Pydantic schemas (data contract)
│   ├── state.py                   # Async SQLite state manager
│   ├── scraper_registry.py        # Module 1: Seed generator
│   ├── crawler_locator.py         # Module 2: Deep crawler
│   ├── parser_text.py             # Module 3: Text extractor
│   ├── llm_engine.py              # Module 4: LLM engine
│   ├── validator.py               # Module 5: Validator
│   ├── exporter.py                # Module 6: Exporter
│   └── utils/
│       ├── browser.py             # Playwright pool with semaphore
│       ├── gdrive.py              # Google Drive URL handler
│       └── retry.py               # Tenacity retry decorators
│
├── tests/                         # Test suite
├── data/                          # Runtime data (gitignored)
│   ├── cache/                     # Seed cache CSVs
│   ├── raw_pdfs/                  # Downloaded documents
│   ├── extracted_text/            # Extracted text files
│   └── output/                    # Final exports
└── logs/                          # Runtime logs (gitignored)
```

## Memory Constraints (8GB RAM)

- Playwright concurrency capped at **4 tabs** via `asyncio.Semaphore`
- Browser memory flush every **50 schools** (configurable)
- Chromium launched with `--disable-gpu --no-sandbox --blink-settings=imagesEnabled=false`
- OCR runs in thread pool via `asyncio.to_thread()` to avoid event loop blocking

## Output

The pipeline produces:
- `data/output/stage1_master_database.xlsx` — Excel export
- `data/output/stage1_master_database.json` — JSON export

## License

MIT
