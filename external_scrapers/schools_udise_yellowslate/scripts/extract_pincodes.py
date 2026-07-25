#!/usr/bin/env python3
"""Extract unique six-digit PIN codes from a KML file into JSON."""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


PINCODE_PATTERN = re.compile(r"^\d{6}$")


def extract_pincodes(kml_path: Path) -> list[str]:
    root = ET.parse(kml_path).getroot()
    pincodes: list[str] = []
    seen: set[str] = set()

    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "SimpleData":
            continue
        if element.attrib.get("name", "").upper() != "PINCODE":
            continue

        pincode = (element.text or "").strip()
        if PINCODE_PATTERN.fullmatch(pincode) and pincode not in seen:
            seen.add(pincode)
            pincodes.append(pincode)

    return pincodes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kml_file", type=Path, help="Input KML file")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("data/input/pincodes.json"),
        help="Output JSON file (default: data/input/pincodes.json)",
    )
    args = parser.parse_args()

    pincodes = extract_pincodes(args.kml_file)
    args.output.write_text(json.dumps(pincodes, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(pincodes)} unique PIN codes to {args.output}")


if __name__ == "__main__":
    main()
