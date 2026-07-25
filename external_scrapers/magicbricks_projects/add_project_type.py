#!/usr/bin/env python3
import json
import os

CLASSIFIED_FILE = "data/processed/bangalore_projects_classified.json"
RAW_FILE = "data/raw/bangalore_projects_enriched.jsonl"
RAW_FALLBACK = "data/raw/bangalore_projects.jsonl"

def classify_type(name, desc):
    name = (name or "").lower()
    desc = (desc or "").lower()
    
    # Check for Villa/House keywords
    if any(k in name or k in desc for k in ["villa", "row house", "rowhouse", "independent house", "residential house", "bungalow", "sanctuary"]):
        return "Villa/House"
        
    # Check for Builder Floor keywords
    if any(k in name or k in desc for k in ["builder floor", "independent floor"]):
        return "Builder Floor"
        
    # Check for Plot/Land keywords
    if any(k in name or k in desc for k in ["plot", "layout", "land", "sites"]):
        return "Plot/Land"
        
    # Default is Apartment
    return "Apartment"

def main():
    if not os.path.exists(CLASSIFIED_FILE):
        print(f"Error: {CLASSIFIED_FILE} does not exist.")
        return

    # 1. Build a lookup map of pdpUrl -> mhDesc from raw/enriched source files
    description_lookup = {}
    sources = [RAW_FILE, RAW_FALLBACK]
    
    for src in sources:
        if os.path.exists(src):
            print(f"Loading description data from {src}...")
            with open(src, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            card = json.loads(line)
                            pdp_url = card.get("pdpUrl")
                            desc = card.get("mhDesc")
                            if pdp_url:
                                description_lookup[pdp_url.strip()] = desc
                        except Exception:
                            pass
                            
    print(f"Loaded descriptions for {len(description_lookup)} unique project URLs.")

    # 2. Load classified projects
    with open(CLASSIFIED_FILE, "r", encoding="utf-8") as f:
        projects = json.load(f)
        
    print(f"Loaded {len(projects)} classified projects.")
    
    # 3. Classify and add project_type field
    stats = {}
    
    for p in projects:
        name = p.get("name")
        url = p.get("url") or ""
        
        # Extract pdpUrl from full URL
        pdp_url = url.split("magicbricks.com/")[-1].strip() if "magicbricks.com/" in url else ""
        
        # Fetch description
        desc = description_lookup.get(pdp_url) or ""
        
        # Classify project type
        p_type = classify_type(name, desc)
        
        # Add to project dict
        p["project_type"] = p_type
        
        # Update statistics
        stats[p_type] = stats.get(p_type, 0) + 1
        
    # 4. Save updated file back
    # First, save a backup
    backup_file = CLASSIFIED_FILE + ".bak_type"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)
    print(f"Saved backup with types to {backup_file}")
    
    # Write back to main classified file
    with open(CLASSIFIED_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)
        
    print("\nProject Type Classification Statistics:")
    for p_type, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / len(projects)) * 100
        print(f"  - {p_type}: {count} ({percentage:.2f}%)")
        
    print(f"\nSuccessfully added 'project_type' to all projects in {CLASSIFIED_FILE}.")

if __name__ == "__main__":
    main()
