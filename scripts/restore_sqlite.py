from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Восстановление SQLite. Приложение должно быть остановлено.")
    parser.add_argument("backup", type=Path)
    parser.add_argument("target", type=Path, nargs="?", default=Path("data/squad_finder.db"))
    args = parser.parse_args()
    if not args.backup.is_file():
        raise SystemExit(f"Резервная копия не найдена: {args.backup}")
    connection = sqlite3.connect(str(args.backup))
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Резервная копия повреждена")
    finally:
        connection.close()
    args.target.parent.mkdir(parents=True, exist_ok=True)
    if args.target.exists():
        safety = args.target.with_suffix(args.target.suffix + ".before_restore")
        shutil.copy2(args.target, safety)
        print(f"Текущая база сохранена: {safety}")
    shutil.copy2(args.backup, args.target)
    print(f"База восстановлена: {args.target}")


if __name__ == "__main__":
    main()
