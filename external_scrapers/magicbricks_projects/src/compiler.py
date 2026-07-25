import os
import pandas as pd
from pathlib import Path

class PipelineCompiler:
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self.processed_dir = Path(self.config.PATHS["processed_dir"])
        self.compiled_file = Path(self.config.PATHS["compiled_file"])

    def compile_all(self):
        self.logger.log("[Compiler] Starting compilation of individual city CSVs...")
        csv_files = []
        
        output_slug = getattr(self.config, "OUTPUT_SLUG", None)
        if output_slug:
            # For focused runs, compile only the file produced by this scrape.
            target_file = self.processed_dir / f"{output_slug}.csv"
            if target_file.exists():
                csv_files.append(target_file)
        else:
            # Gather all processed city files, skipping the template or previously compiled
            exclude = ["template.csv", self.compiled_file.name]
            for f in self.processed_dir.glob("*.csv"):
                if f.name not in exclude:
                    csv_files.append(f)
                
        if not csv_files:
            self.logger.log("[Compiler] No valid city CSV files found to compile.")
            return

        all_dfs = []
        total_rows = 0
        
        for file in csv_files:
            try:
                # The filename represents the city_name 
                city_str = file.stem.replace("_", " ").title()
                df = pd.read_csv(file, low_memory=False)
                # Introduce identifying column
                df.insert(0, "search_city", city_str)
                all_dfs.append(df)
                total_rows += len(df)
                self.logger.log(f"[Compiler] Appended {city_str} ({len(df):,} records).")
            except Exception as e:
                self.logger.log(f"[Compiler] Failed reading {file.name}: {e}")
                
        if all_dfs:
            combined_df = pd.concat(all_dfs, ignore_index=True)
            # Remove any absolute duplicates across datasets if necessary
            initial_count = len(combined_df)
            combined_df.drop_duplicates(subset=["listing_id"], inplace=True)
            final_count = len(combined_df)
            
            combined_df.to_csv(self.compiled_file, index=False)
            
            self.logger.log(f"[Compiler] Success! Compiled {final_count:,} unique listings across {len(csv_files)} cities.")
            if initial_count > final_count:
                self.logger.log(f"[Compiler] Note: Removed {initial_count - final_count:,} cross-city duplicate listing IDs.")
