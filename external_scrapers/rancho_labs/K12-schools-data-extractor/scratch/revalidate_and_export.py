import asyncio
import logging
import sys
from pathlib import Path

# Add project root directory to PYTHONPATH
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from src.state import StateManager
from src.validator import validate_school
from src.exporter import export_master_database

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s"
    )
    
    async with StateManager() as state_mgr:
        print("Fetching all processed/validated schools to update their pincodes and geocode queries...")
        # Get all schools that have already been validated or exported
        cursor = await state_mgr._conn.execute(
            "SELECT * FROM schools WHERE status IN ('VALIDATED', 'EXPORTED')"
        )
        rows = await cursor.fetchall()
        schools_to_update = [dict(r) for r in rows]
        print(f"Found {len(schools_to_update)} schools to update.")
        
        updated_count = 0
        for i, school in enumerate(schools_to_update, 1):
            school_id = school["school_id"]
            # Re-validate this school which will update its geocode_query and pincode from the updated schools table
            # E.g. validate_school reads the current fields in the DB row and updates the validated record.
            # But wait, validate_school reads from the 'school_row' parameter we pass in. So let's fetch the fresh row from DB first!
            fresh_school = await state_mgr.get_school(school_id)
            if fresh_school:
                result = await validate_school(school_id, fresh_school, state_mgr)
                if result:
                    updated_count += 1
            if i % 100 == 0 or i == len(schools_to_update):
                print(f"Progress: {i} / {len(schools_to_update)} updated.")
                
        print(f"Successfully re-validated {updated_count} schools with updated pincodes.")
        
        print("\nStarting Re-Export stage...")
        xlsx_path, json_path = await export_master_database(state_mgr, include_failed=True)
        print("Re-Export complete!")
        print(f"Excel file: {xlsx_path}")
        print(f"JSON file:  {json_path}")

if __name__ == "__main__":
    asyncio.run(main())
