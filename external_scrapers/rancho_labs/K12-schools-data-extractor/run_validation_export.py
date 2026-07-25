import asyncio
import logging
import sys
from pathlib import Path

# Add project root directory to PYTHONPATH
root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from src.state import StateManager
from src.validator import validate_all_pending
from src.exporter import export_master_database

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s"
    )
    
    async with StateManager() as state_mgr:
        print("Starting Validation stage...")
        val_count = await validate_all_pending(state_mgr)
        print(f"Validation complete: validated {val_count} schools.")
        
        print("\nStarting Export stage...")
        xlsx_path, json_path = await export_master_database(state_mgr, include_failed=False)
        print("Export complete!")
        print(f"Excel file: {xlsx_path}")
        print(f"JSON file:  {json_path}")

if __name__ == "__main__":
    asyncio.run(main())
