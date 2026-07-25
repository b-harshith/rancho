#!/usr/bin/env python3
import json
import os

INPUT_FILE = "data/raw/bangalore_projects.jsonl"
GEOCODED_FILE = "data/raw/bangalore_projects_geocoded_free.jsonl"

PLOT_KEYWORDS = ['plot', 'plots', 'land', 'layout', 'site', 'sites']

def is_plot(card):
    name = (card.get("psmName") or "").lower()
    desc = (card.get("mhDesc") or "").lower()
    return any(kw in name or kw in desc for kw in PLOT_KEYWORDS)

def filter_file(filepath):
    if not os.path.exists(filepath):
        print(f"File {filepath} does not exist. Skipping.")
        return 0, 0
        
    temp_filepath = filepath + ".tmp"
    total_before = 0
    total_after = 0
    removed_count = 0
    
    with open(filepath, "r", encoding="utf-8") as fin, open(temp_filepath, "w", encoding="utf-8") as fout:
        for line in fin:
            if line.strip():
                total_before += 1
                try:
                    card = json.loads(line)
                    if is_plot(card):
                        removed_count += 1
                    else:
                        fout.write(json.dumps(card, ensure_ascii=False) + "\n")
                        total_after += 1
                except Exception:
                    # Keep lines that fail parsing just in case, or write them back
                    fout.write(line)
                    total_after += 1
                    
    # Replace old file with filtered one
    os.replace(temp_filepath, filepath)
    print(f"Filtered {filepath}:")
    print(f"  - Total records before: {total_before}")
    print(f"  - Removed plot/land records: {removed_count}")
    print(f"  - Total records remaining: {total_after}\n")
    return total_before, total_after

def main():
    print("=== Filtering out Plot / Land / Layout projects ===\n")
    filter_file(INPUT_FILE)
    filter_file(GEOCODED_FILE)
    print("Done! Plot/land listings have been removed.")

if __name__ == "__main__":
    main()
