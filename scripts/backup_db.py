from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

from app.backup_service import create_backup


async def main() -> None:
    path = await create_backup()
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
