#!/usr/bin/env python3
"""Browser-backed YellowSlate fee scraper.

Why this exists:
  YellowSlate's direct /search RSC URL needs browser city state. Plain HTTP can
  return "Your search results need City" or a Next.js error digest, while a real
  browser session that first opens /schools/bengaluru returns the expected
  fee-filtered search pages.

This scraper:
  1. Opens https://yellowslate.com/schools/bengaluru once to initialize city.
  2. Loads each fee-bracket search page:
       https://yellowslate.com/search?fee=0-30000&_rsc=i31tq&page=2
  3. Extracts each visible school card, including the YellowSlate school URL.
  4. Saves raw observations + deduped normalized JSON.

Example:
  python3 scripts/scrape_yellowslate_browser.py --workers 8

Debug:
  python3 scripts/scrape_yellowslate_browser.py --max-pages-per-bracket 1 --headful
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/output/yellowslate"
BASE_URL = "https://yellowslate.com"
DEFAULT_RSC = "i31tq"
CHROME_CANDIDATES = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
]


@dataclass(frozen=True)
class FeeBracket:
    key: str
    label: str
    fee_param: str
    min_fee: int
    max_fee: int | None
    total_pages: int


FEE_BRACKETS = [
    FeeBracket("under_30k", "Under 30 K", "0-30000", 0, 30000, 72),
    FeeBracket("30k_50k", "Above 30 K And Under 50 K", "30000-50000", 30000, 50000, 73),
    FeeBracket("50k_70k", "Above 50 K And Under 70 K", "50000-70000", 50000, 70000, 30),
    FeeBracket("70k_1l", "Above 70 K And Under 1 Lac", "70000-100000", 70000, 100000, 18),
    FeeBracket("1l_2l", "Above 1 Lac And Under 2 Lac", "100000-200000", 100000, 200000, 23),
    FeeBracket("above_2l", "Above 2 Lac", "200000-99999999", 200000, None, 3),
]


CARD_EXTRACTOR_JS = r"""
() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const cleanLines = (s) => (s || "")
    .split(/\n+/)
    .map(x => clean(x))
    .filter(Boolean);

  const allLines = cleanLines(document.body?.innerText || "");
  const isFee = (x) => /₹|N\/A\s*-\s*N\/A/i.test(x || "");
  const isAction = (x) => /^(Enquire Now|Read more\.{0,3}|Add to Compare)$/i.test(x || "");

  const readMoreLinks = Array.from(document.querySelectorAll('a[href*="/school/"]'))
    .filter(a => /^Read more\.{0,3}$/i.test(clean(a.innerText || a.textContent || "")));

  const cards = [];
  const seen = new Set();
  for (const link of readMoreLinks) {
    const href = link.href;
    if (!href || seen.has(href)) continue;
    seen.add(href);

    let best = link;
    let node = link;
    for (let depth = 0; depth < 10 && node && node.parentElement; depth++) {
      node = node.parentElement;
      const lines = cleanLines(node.innerText || node.textContent || "");
      const readMoreCount = Array.from(node.querySelectorAll('a[href*="/school/"]'))
        .filter(a => /^Read more\.{0,3}$/i.test(clean(a.innerText || a.textContent || ""))).length;
      const hasFee = lines.some(isFee);
      const hasActions = lines.some(x => /^Enquire Now$/i.test(x)) && lines.some(x => /^Read more\.{0,3}$/i.test(x));
      if (readMoreCount === 1 && hasFee && hasActions && lines.length >= 4 && lines.length <= 10) {
        best = node;
        break;
      }
    }

    const lines = cleanLines(best.innerText || best.textContent || "");
    cards.push({
      school_url: href,
      anchor_text: clean(link.innerText || link.textContent || ""),
      raw_text: lines.join("\n"),
      lines: lines.filter(x => !isAction(x))
    });
  }

  return {
    title: document.title,
    url: location.href,
    body_head: (document.body?.innerText || "").slice(0, 1000),
    cards,
    debug: {
      read_more_links: readMoreLinks.length,
      cards: cards.length,
      line_sample: allLines.slice(0, 40)
    }
  };
}
"""


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def build_url(bracket: FeeBracket, page: int, rsc: str) -> str:
    params = {"fee": bracket.fee_param, "_rsc": rsc}
    if page > 1:
        params["page"] = str(page)
    return f"{BASE_URL}/search?{urlencode(params)}"


def parse_money(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    return int(digits)


def parse_fee_line(line: str | None) -> dict[str, Any]:
    if not line:
        return {"min_fee": None, "max_fee": None, "fee_text": None}
    text = line.strip()
    if re.search(r"N/A\s*-\s*N/A", text, re.I):
        return {"min_fee": None, "max_fee": None, "fee_text": text}
    parts = re.split(r"\s*-\s*", text)
    if len(parts) >= 2:
        return {"min_fee": parse_money(parts[0]), "max_fee": parse_money(parts[1]), "fee_text": text}
    amount = parse_money(text)
    return {"min_fee": amount, "max_fee": amount, "fee_text": text}


def infer_fields(lines: list[str], url: str) -> dict[str, Any]:
    ignored = {"Enquire Now", "Read more...", "Read more", "Add School for Free in 5 Mins", "Book A Demo"}
    useful = [x for x in lines if x not in ignored]

    fee_index = None
    for i, line in enumerate(useful):
        if "₹" in line or re.search(r"N/A\s*-\s*N/A", line, re.I):
            fee_index = i
            break

    fee_line = useful[fee_index] if fee_index is not None else None
    before_fee = useful[:fee_index] if fee_index is not None else useful

    # Typical card lines:
    #   Board
    #   School Name
    #   Area
    #   ₹x - ₹y / N/A - N/A
    board = before_fee[0] if len(before_fee) >= 1 else None
    school_name = before_fee[1] if len(before_fee) >= 2 else None
    area = before_fee[2] if len(before_fee) >= 3 else None

    # If the anchor collapsed text into one line, fall back to URL slug.
    if not school_name:
        slug = url.rstrip("/").split("/")[-1]
        school_name = re.sub(r"-+", " ", slug).title()

    return {
        "board_text": board,
        "school_name": school_name,
        "area": area,
        **parse_fee_line(fee_line),
    }


def fee_fits_bracket(min_fee: int | None, max_fee: int | None, bracket: FeeBracket) -> bool | None:
    value = min_fee if min_fee is not None else max_fee
    if value is None:
        return None
    if bracket.max_fee is None:
        return value >= bracket.min_fee
    return bracket.min_fee <= value <= bracket.max_fee


async def scrape_one_page(context, bracket: FeeBracket, page_no: int, args) -> dict[str, Any]:
    url = build_url(bracket, page_no, args.rsc)
    page = await context.new_page()
    try:
        for attempt in range(1, args.retries + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
                await page.wait_for_timeout(args.settle_ms)
                data = await page.evaluate(CARD_EXTRACTOR_JS)
                cards = data.get("cards", [])
                body_head = data.get("body_head", "")
                if cards or attempt == args.retries:
                    return {
                        "bracket": bracket,
                        "page": page_no,
                        "url": url,
                        "title": data.get("title"),
                        "body_head": body_head,
                        "cards": cards,
                        "error": None,
                    }
            except PlaywrightTimeoutError as exc:
                if attempt == args.retries:
                    return {
                        "bracket": bracket,
                        "page": page_no,
                        "url": url,
                        "title": None,
                        "body_head": "",
                        "cards": [],
                        "error": f"timeout: {exc}",
                    }
            except Exception as exc:  # noqa: BLE001
                if attempt == args.retries:
                    return {
                        "bracket": bracket,
                        "page": page_no,
                        "url": url,
                        "title": None,
                        "body_head": "",
                        "cards": [],
                        "error": repr(exc),
                    }
            await page.wait_for_timeout(500 * attempt)
    finally:
        await page.close()


async def scrape_all(args) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks: list[tuple[FeeBracket, int]] = []
    selected = [b for b in FEE_BRACKETS if args.only_bracket in (None, b.key)]
    for bracket in selected:
        pages = bracket.total_pages
        if args.max_pages_per_bracket:
            pages = min(pages, args.max_pages_per_bracket)
        for page_no in range(1, pages + 1):
            tasks.append((bracket, page_no))

    async with async_playwright() as p:
        executable_path = args.browser_executable
        if not executable_path:
            for candidate in CHROME_CANDIDATES:
                if candidate.exists():
                    executable_path = str(candidate)
                    break
        launch_kwargs = {"headless": not args.headful}
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
            logging.info("Using browser executable: %s", executable_path)
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        init_page = await context.new_page()
        logging.info("Initializing YellowSlate city state: /schools/%s", args.city)
        await init_page.goto(f"{BASE_URL}/schools/{args.city}", wait_until="domcontentloaded", timeout=args.timeout * 1000)
        await init_page.wait_for_timeout(2500)
        await init_page.close()

        semaphore = asyncio.Semaphore(args.workers)
        page_reports: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []

        async def run_task(idx: int, bracket: FeeBracket, page_no: int) -> None:
            async with semaphore:
                result = await scrape_one_page(context, bracket, page_no, args)
                cards = result["cards"]
                logging.info(
                    "[%s/%s] %s page %s cards=%s error=%s",
                    idx,
                    len(tasks),
                    bracket.key,
                    page_no,
                    len(cards),
                    result["error"] or "-",
                )
                page_reports.append(
                    {
                        "bracket_key": bracket.key,
                        "bracket_label": bracket.label,
                        "page": page_no,
                        "url": result["url"],
                        "title": result["title"],
                        "cards": len(cards),
                        "error": result["error"],
                        "body_head": result["body_head"],
                    }
                )
                for card in cards:
                    parsed = infer_fields(card.get("lines") or [], card["school_url"])
                    records.append(
                        {
                            "source": "yellowslate",
                            "school_name": parsed["school_name"],
                            "school_url": card["school_url"],
                            "board_text": parsed["board_text"],
                            "area": parsed["area"],
                            "fee": {
                                "min_fee": parsed["min_fee"],
                                "max_fee": parsed["max_fee"],
                                "fee_text": parsed["fee_text"],
                                "search_bracket_key": bracket.key,
                                "search_bracket_label": bracket.label,
                                "search_bracket_min": bracket.min_fee,
                                "search_bracket_max": bracket.max_fee,
                                "fee_fits_bracket": fee_fits_bracket(parsed["min_fee"], parsed["max_fee"], bracket),
                            },
                            "yellowslate_meta": {
                                "source_page": page_no,
                                "source_url": result["url"],
                                "anchor_text": card.get("anchor_text"),
                                "raw_card_text": card.get("raw_text"),
                                "raw_lines": card.get("lines"),
                            },
                        }
                    )

        await asyncio.gather(*(run_task(i, b, pno) for i, (b, pno) in enumerate(tasks, start=1)))
        await context.close()
        await browser.close()

    return records, page_reports


def merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for record in records:
        key = record["school_url"]
        if key not in by_url:
            record["observed_fee_brackets"] = []
            by_url[key] = record
        by_url[key]["observed_fee_brackets"].append(
            {
                "bracket_key": record["fee"]["search_bracket_key"],
                "bracket_label": record["fee"]["search_bracket_label"],
                "source_page": record["yellowslate_meta"]["source_page"],
                "source_url": record["yellowslate_meta"]["source_url"],
                "fee_text": record["fee"]["fee_text"],
                "fee_fits_bracket": record["fee"]["fee_fits_bracket"],
            }
        )
        # Prefer a record with concrete fee over N/A.
        current = by_url[key]
        if current["fee"]["min_fee"] is None and record["fee"]["min_fee"] is not None:
            keep_observed = current["observed_fee_brackets"]
            record["observed_fee_brackets"] = keep_observed
            by_url[key] = record
    return sorted(by_url.values(), key=lambda x: (x["school_name"] or "", x["school_url"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", default="bengaluru", help="City name (e.g. bengaluru, delhi, gurugram)")
    parser.add_argument("--rsc", default=DEFAULT_RSC)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--settle-ms", type=int, default=1200)
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--browser-executable", default=None, help="Path to Chrome/Chromium executable")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--max-pages-per-bracket", type=int, default=None)
    parser.add_argument("--only-bracket", choices=[b.key for b in FEE_BRACKETS], default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    records, page_reports = asyncio.run(scrape_all(args))
    schools = merge_records(records)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_total_from_user": 2871,
        "raw_card_records": len(records),
        "unique_school_urls": len(schools),
        "pages_requested": len(page_reports),
        "records_by_bracket": {
            bracket.key: sum(1 for r in records if r["fee"]["search_bracket_key"] == bracket.key)
            for bracket in FEE_BRACKETS
        },
        "unique_by_observed_bracket": {
            bracket.key: len(
                {r["school_url"] for r in records if r["fee"]["search_bracket_key"] == bracket.key}
            )
            for bracket in FEE_BRACKETS
        },
        "fee_fit_counts": {
            str(value): sum(1 for r in records if r["fee"]["fee_fits_bracket"] is value)
            for value in (True, False, None)
        },
        "pages_with_zero_cards": [p for p in page_reports if p["cards"] == 0],
        "pages_with_errors": [p for p in page_reports if p["error"]],
        "page_reports": sorted(page_reports, key=lambda x: (x["bracket_key"], x["page"])),
    }

    (OUT_DIR / f"yellowslate_browser_fee_schools_{args.city}.json").write_text(
        json.dumps(schools, ensure_ascii=False, indent=2) + "\n"
    )
    (OUT_DIR / f"yellowslate_browser_fee_raw_cards_{args.city}.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    )
    (OUT_DIR / f"yellowslate_browser_fee_scrape_report_{args.city}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )

    print(json.dumps({k: report[k] for k in ("pages_requested", "raw_card_records", "unique_school_urls", "records_by_bracket", "pages_with_zero_cards", "pages_with_errors")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
