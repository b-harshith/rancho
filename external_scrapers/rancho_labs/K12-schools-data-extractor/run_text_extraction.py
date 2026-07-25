import asyncio, sys
sys.path.append('.')
from src.parser_text import extract_all_pending
from src.state import StateManager

async def main():
    async with StateManager() as state_mgr:
        await extract_all_pending(state_mgr)

if __name__ == "__main__":
    asyncio.run(main())
