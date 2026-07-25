import asyncio
import logging
import sys
from pathlib import Path

# Add project root directory to PYTHONPATH
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from src.state import StateManager
from src.llm_engine import process_all_pending

async def main():
    # Configure logging to go to a separate log file as well as stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        handlers=[
            logging.FileHandler("logs/llm_processing.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    async with StateManager() as state_mgr:
        processed_count = await process_all_pending(state_mgr)
        print(f"LLM processing finished. Successfully processed {processed_count} schools.")

if __name__ == "__main__":
    asyncio.run(main())
