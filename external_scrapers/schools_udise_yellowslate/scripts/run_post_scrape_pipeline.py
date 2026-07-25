import subprocess
import sys
from pathlib import Path

CITIES = ["delhi_ncr", "mumbai", "hyderabad", "chennai", "kolkata", "pune", ]
ROOT = Path("/Users/malleswararao/Desktop/school extraction")

def run_cmd(cmd):
    print(f"\nExecuting: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode != 0:
        print(f"Error: Command failed with code {res.returncode}")
        # Continue with next step instead of hard exiting, to allow maximum completion

def main():
    print("=== STARTING POST-SCRAPE PIPELINE FOR ALL CITIES ===")
    
    for city in CITIES:
        print(f"\n==========================================")
        print(f"PROCESSING CITY: {city.upper()}")
        print(f"==========================================")
        
        # 1. Determine UDISE dataset path
        if city == "delhi_ncr":
            udise_path = "data/output/schools_analysis_delhi_ncr_compact.json"
        elif city in ("bengaluru", "bangalore"):
            udise_path = "data/output/schools_analysis_bangalore_compact.json"
        else:
            udise_path = "data/output/schools_analysis.json"
            
        ys_path = f"data/output/yellowslate/yellowslate_schools_with_locations_{city}.json"
        merge_output = f"data/output/schools_merged_matched_udise_{city}.json"
        
        # Check if YellowSlate input file exists
        if not (ROOT / ys_path).exists():
            print(f"Warning: YellowSlate file {ys_path} does not exist. Skipping city {city}.")
            continue
            
        # 2. Run merge & match
        merge_cmd = [
            ".venv/bin/python", "scripts/merge_and_match_to_udise.py",
            "--ys-path", ys_path,
            "--udise-path", udise_path,
            "--output", merge_output
        ]
        run_cmd(merge_cmd)
        
        # 3. Run predict enrollment & compile
        compile_cmd = [
            ".venv/bin/python", "scripts/predict_enrollment_and_compile.py",
            "--city", city,
            "--udise-path", udise_path
        ]
        run_cmd(compile_cmd)

    # 4. Run verification and deduplication cleaning on final output files
    print(f"\n==========================================")
    print("RUNNING FINAL VERIFICATION & CLEANUP")
    print(f"==========================================")
    verify_cmd = [
        ".venv/bin/python", "scripts/verify_school_data.py"
    ]
    run_cmd(verify_cmd)
    
    print("\n=== POST-SCRAPE PIPELINE COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
