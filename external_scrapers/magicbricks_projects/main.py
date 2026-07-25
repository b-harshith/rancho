import sys
import argparse
import traceback

import config
from src.logger import PipelineLogger
from src.scraper import MagicbricksScraper
from src.parser import MagicbricksParser
from src.compiler import PipelineCompiler

def run_pipeline(city_list, scrape_only=False):
    """Orchestrates the scraping, parsing, and compiling process for the given cities."""
    logger = PipelineLogger(total_cities=len(city_list))
    
    try:
        logger.start()
        logger.log(f"[Main] Initializing Flent Lens Pipeline for {len(city_list)} cities...")
        
        scraper = MagicbricksScraper(logger, config)
        parser = MagicbricksParser(logger, config)
        compiler = PipelineCompiler(logger, config)
        
        for idx, city in enumerate(city_list, 1):
            # 1. Scrape City Data
            logger.update_city(city, "Scraping Phase", idx)
            scraper.scrape_city(city)
            
            # 2. Parse Raw JSONL to CSV
            if not scrape_only:
                logger.update_city(city, "Parsing Phase", idx)
                parser.process_city(city)
            
        # 3. Compile all CSVs into final dataset
        if not scrape_only:
            logger.update_city("All Destinations", "Compilation Phase", len(city_list))
            compiler.compile_all()
        
        logger.log(f"[Main] Pipeline completed successfully Across {len(city_list)} cities!")
        
    except KeyboardInterrupt:
        logger.log("[Main] Pipeline gracefully interrupted by user. Stopping background threads...")
        sys.exit(130)
    except Exception as e:
        logger.log(f"[Main] Critical Pipeline Error: {e}")
        # Uncomment below if you need detailed traceback tracking in logs
        # logger.log(traceback.format_exc()) 
    finally:
        # Crucial to call stop so the shell doesn't break
        logger.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-City Real Estate Extractor")
    parser.add_argument("--city", help="Run pipeline for a specific single city", type=str)
    parser.add_argument("--scrape-only", action="store_true", help="Only run the scraper, skip parsing and compiling")
    args = parser.parse_args()

    if args.city:
        run_pipeline([args.city.replace("_", " ").title()], scrape_only=args.scrape_only)
    else:
        run_pipeline(config.TARGET_CITIES, scrape_only=args.scrape_only)
