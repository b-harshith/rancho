#!/usr/bin/env python3
"""Agentic Gemini verifier for the 6,312 premium-school candidate master.

This script sends one school at a time to Gemini and asks for a structured
branch-level verdict:

- Is this the right school/branch for the supplied location?
- Is the school genuinely premium, or a false positive?
- What is the best branch website if discoverable?
- What evidence supports the verdict?

The script is intentionally resumable. It writes JSONL after every school and
skips IDs already present in the JSONL on reruns.

Usage:
  export GEMINI_API_KEY="YOUR_KEY"
  python3 scripts/agentic_verify_premium_schools_gemini.py --limit 25
  python3 scripts/agentic_verify_premium_schools_gemini.py --city delhi_ncr

For grounding/search, keep --use-search enabled. If your Gemini model/API
version rejects the google_search tool, rerun with --no-use-search.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "output/final_master_premium_schools_6312.geojson"
DEFAULT_JSONL = ROOT / "output/agentic_premium_school_verification_gemini.jsonl"
DEFAULT_CSV = ROOT / "output/agentic_premium_school_verification_gemini.csv"


SYSTEM_INSTRUCTION = """You are a careful India K-12 school market analyst.
Your job is to verify whether a specific school branch is genuinely premium.

Be conservative. Do not mark a school premium just because its name contains
"Public School", "International", "Global", "Academy", or "English Medium".

Premium means one or more of:
- Known high-fee / elite / aspirational private K-12 school chain or branch.
- Strong evidence of annual fee usually above INR 1 lakh, or comparable premium positioning.
- Premium board/curriculum such as IB, Cambridge/IGCSE, CISCE/ICSE, or high-end CBSE chain.
- Established brand with high parent demand, strong facilities, or elite positioning.

Usually NOT premium:
- Small local state-board schools.
- Generic "public school" names with weak evidence.
- Low-enrollment unknown schools unless there is strong evidence it is intentionally boutique/premium.
- Play schools, nursery-only, KG-only, daycare, creche, anganwadi, or preschool chains.
- Government, aided, municipal, trust-run low-fee, or unrecognized low-end schools.

You must verify branch/location fit. If the supplied location appears to point
to a different branch or wrong school, say so.

Return only valid JSON. Do not include markdown."""


def build_user_prompt(school: dict[str, Any]) -> str:
    p = school.get("properties", {}) or {}
    coords = None
    if school.get("geometry") and school["geometry"].get("coordinates"):
        lon, lat = school["geometry"]["coordinates"][:2]
        coords = {"latitude": lat, "longitude": lon}

    compact = {
        "school_name": p.get("school_name"),
        "udise_code": p.get("udise_code"),
        "city": p.get("city"),
        "state": p.get("state"),
        "district": p.get("district"),
        "area": p.get("area"),
        "address": p.get("address"),
        "pincode": p.get("pincode"),
        "coordinates": coords,
        "board_from_data": p.get("board"),
        "chain_detected_by_model": p.get("chain_detected"),
        "record_type": p.get("record_type"),
        "premium_basis_from_pipeline": p.get("premium_basis"),
        "pipeline_confidence": p.get("confidence"),
        "fee_reference_if_known": p.get("fee_reference"),
        "k12_enrollment": p.get("enrollment_total"),
        "grade_2_9_enrollment_est": p.get("estimated_grade_2_9_student_count"),
        "google_place_id_from_data": p.get("google_place_id")
        or p.get("udise_google_place_id_backfill"),
        "google_place_website_from_data": p.get("google_place_website"),
        "google_maps_url_from_data": p.get("google_place_maps_url"),
        "source_url_from_data": p.get("source_url"),
        "google_formatted_address_from_data": p.get("google_formatted_address"),
        "audit_note_from_pipeline": p.get("audit_note"),
    }

    return f"""Verify this school branch as a premium-school candidate.

School details from our local data:
{json.dumps(compact, ensure_ascii=False, indent=2)}

Tasks:
1. Check whether this is the right real-world school branch for the supplied city/location.
2. If possible, identify the official website for this exact branch or best official school website.
3. Decide whether this school should be counted as premium for private K-12 market sizing.
4. Be especially careful with generic names such as "Public School", "International School",
   "Global School", "Academy", and low-enrollment schools.
5. If it appears to be a preschool/KG/daycare/nursery-only listing, mark it not premium for K-12.

Return JSON matching this schema:
{{
  "school_name_checked": "string",
  "is_right_school_branch": true/false/null,
  "location_verdict": "right_location | likely_right_location | wrong_location | insufficient_evidence",
  "corrected_branch_name": "string or null",
  "official_website": "string or null",
  "website_confidence": "high | medium | low | none",
  "premium_decision": "premium | not_premium | uncertain",
  "premium_confidence": 0.0,
  "premium_tier": "elite | premium | upper_mid | mass_private | preschool_only | uncertain",
  "likely_fee_band": "below_75k | 75k_to_1L | 1L_to_1_5L | above_1_5L | unknown",
  "reasons": ["short reason 1", "short reason 2"],
  "negative_flags": ["generic_public_school_name", "low_enrollment", "state_board_local", "preschool_only", "weak_evidence", "wrong_branch", "other"],
  "evidence": [
    {{
      "claim": "short evidence claim",
      "source": "website/search/source name or null",
      "url": "source URL or null"
    }}
  ],
  "recommended_action": "keep_as_premium | remove_false_positive | manual_review | fix_branch_or_website"
}}

Important:
- premium_confidence must be a number from 0 to 1.
- Use null when you cannot verify something.
- Do not invent exact fees without evidence.
- Return only JSON."""


def school_key(feature: dict[str, Any], index: int) -> str:
    p = feature.get("properties", {}) or {}
    code = str(p.get("udise_code") or "").strip()
    if code:
        return f"udise:{code}"
    place = str(p.get("google_place_id") or p.get("udise_google_place_id_backfill") or "").strip()
    if place:
        return f"place:{place}"
    name = str(p.get("school_name") or "").strip().lower()
    city = str(p.get("city") or "").strip().lower()
    lat = p.get("latitude")
    lon = p.get("longitude")
    return f"row:{index}:{city}:{name}:{lat}:{lon}"


def load_features(path: Path, city: str | None) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", [])
    if city:
        features = [
            f for f in features
            if (f.get("properties", {}) or {}).get("city") == city
        ]
    return features


def load_done_keys(jsonl_path: Path) -> set[str]:
    done: set[str] = set()
    if not jsonl_path.exists():
        return done
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get("school_key")
            if key:
                done.add(key)
    return done


def gemini_generate(
    api_key: str,
    model: str,
    prompt: str,
    use_search: bool,
    temperature: float,
    timeout: int,
) -> dict[str, Any]:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload: dict[str, Any] = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_INSTRUCTION}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "response_mime_type": "application/json",
        },
    }
    if use_search:
        payload["tools"] = [{"google_search": {}}]

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_text_and_metadata(response: dict[str, Any]) -> tuple[str, Any]:
    candidates = response.get("candidates") or []
    if not candidates:
        return "", None
    cand = candidates[0]
    parts = ((cand.get("content") or {}).get("parts") or [])
    text = "".join(part.get("text", "") for part in parts)
    return text, cand.get("groundingMetadata")


def parse_model_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        # Defensive cleanup for rare fenced JSON responses.
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1]), None
            except json.JSONDecodeError:
                pass
        return None, str(e)


def flatten_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    p = row.get("input_properties", {}) or {}
    v = row.get("verification", {}) or {}
    return {
        "school_key": row.get("school_key"),
        "school_name": p.get("school_name"),
        "city": p.get("city"),
        "udise_code": p.get("udise_code"),
        "record_type": p.get("record_type"),
        "chain_detected": p.get("chain_detected"),
        "board": p.get("board"),
        "enrollment_total": p.get("enrollment_total"),
        "pipeline_confidence": p.get("confidence"),
        "is_right_school_branch": v.get("is_right_school_branch"),
        "location_verdict": v.get("location_verdict"),
        "corrected_branch_name": v.get("corrected_branch_name"),
        "official_website": v.get("official_website"),
        "website_confidence": v.get("website_confidence"),
        "premium_decision": v.get("premium_decision"),
        "premium_confidence": v.get("premium_confidence"),
        "premium_tier": v.get("premium_tier"),
        "likely_fee_band": v.get("likely_fee_band"),
        "recommended_action": v.get("recommended_action"),
        "reasons": " | ".join(v.get("reasons") or []),
        "negative_flags": " | ".join(v.get("negative_flags") or []),
        "error": row.get("error"),
    }


def rebuild_csv(jsonl_path: Path, csv_path: Path) -> None:
    rows = []
    if not jsonl_path.exists():
        return
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(flatten_for_csv(json.loads(line)))
            except Exception:
                continue
    if not rows:
        return
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output-jsonl", type=Path, default=DEFAULT_JSONL)
    ap.add_argument("--output-csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--city", choices=[
        "bengaluru", "chennai", "delhi_ncr", "hyderabad", "kolkata", "mumbai", "pune"
    ])
    ap.add_argument("--limit", type=int, help="Process only N pending schools, useful for testing.")
    ap.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between requests.")
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--temperature", type=float, default=0.1)
    ap.add_argument("--use-search", dest="use_search", action="store_true", default=True)
    ap.add_argument("--no-use-search", dest="use_search", action="store_false")
    ap.add_argument("--rebuild-csv-only", action="store_true")
    args = ap.parse_args()

    if args.rebuild_csv_only:
        rebuild_csv(args.output_jsonl, args.output_csv)
        print(f"CSV rebuilt: {args.output_csv}")
        return 0

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY. Run: export GEMINI_API_KEY='YOUR_KEY'", file=sys.stderr)
        return 2

    features = load_features(args.input, args.city)
    done = load_done_keys(args.output_jsonl)
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    pending: list[tuple[int, dict[str, Any], str]] = []
    for i, feature in enumerate(features):
        key = school_key(feature, i)
        if key not in done:
            pending.append((i, feature, key))

    if args.limit:
        pending = pending[:args.limit]

    print(f"Input schools: {len(features)}")
    print(f"Already done: {len(done)}")
    print(f"Pending this run: {len(pending)}")
    print(f"Output JSONL: {args.output_jsonl}")
    print(f"Output CSV: {args.output_csv}")

    processed = 0
    with args.output_jsonl.open("a", encoding="utf-8") as out:
        for idx, feature, key in pending:
            p = feature.get("properties", {}) or {}
            print(f"[{processed + 1}/{len(pending)}] {p.get('city')} | {p.get('school_name')} | {key}", flush=True)
            prompt = build_user_prompt(feature)

            response = None
            error = None
            for attempt in range(args.max_retries + 1):
                try:
                    response = gemini_generate(
                        api_key=api_key,
                        model=args.model,
                        prompt=prompt,
                        use_search=args.use_search,
                        temperature=args.temperature,
                        timeout=args.timeout,
                    )
                    error = None
                    break
                except urllib.error.HTTPError as e:
                    body = e.read().decode("utf-8", errors="replace")
                    error = f"HTTP {e.code}: {body[:1000]}"
                    if e.code in {400, 401, 403}:
                        break
                except Exception as e:
                    error = repr(e)

                wait = min(60, (2 ** attempt) * 2)
                print(f"  retry {attempt + 1}/{args.max_retries} after error: {error[:180]}", flush=True)
                time.sleep(wait)

            text = ""
            grounding = None
            verification = None
            parse_error = None
            if response is not None:
                text, grounding = extract_text_and_metadata(response)
                verification, parse_error = parse_model_json(text)

            row = {
                "school_key": key,
                "input_index": idx,
                "input_properties": p,
                "verification": verification,
                "raw_model_text": text,
                "grounding_metadata": grounding,
                "model": args.model,
                "used_search": args.use_search,
                "error": error or parse_error,
                "created_at_unix": int(time.time()),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            processed += 1

            if processed % 25 == 0:
                rebuild_csv(args.output_jsonl, args.output_csv)
            if args.sleep > 0:
                time.sleep(args.sleep)

    rebuild_csv(args.output_jsonl, args.output_csv)
    print(f"Done. Processed: {processed}")
    print(f"JSONL: {args.output_jsonl}")
    print(f"CSV: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
