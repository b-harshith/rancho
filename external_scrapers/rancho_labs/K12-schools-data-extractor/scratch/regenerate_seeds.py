import asyncio
import sys
import logging
from pathlib import Path

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    stream=sys.stdout
)

# Add project root directory to PYTHONPATH
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from src.scraper_registry import generate_seed_list
from src.state import StateManager
from src.utils.browser import BrowserPool

async def main():
    print("Initializing StateManager and BrowserPool...")
    async with StateManager() as state_mgr:
        pool = BrowserPool()
        await pool.start()
        
        try:
            print("Starting live seed regeneration for 'bangalore' with fixed scraper...")
            # Set force_rescrape=True to bypass cache read and perform live CBSE scraping
            df = await generate_seed_list(
                city="bangalore",
                pool=pool,
                state_mgr=state_mgr,
                force_rescrape=True
            )
            print(f"Seed generation finished. Total unique seeds in cache: {len(df)}")
            print("Board counts:")
            print(df["Board"].value_counts())
            print("Locality/District counts:")
            print(df["Locality"].value_counts())
        except Exception as e:
            print(f"Error during seed regeneration: {e}")
        finally:
            await pool.stop()

if __name__ == "__main__":
    asyncio.run(main())
