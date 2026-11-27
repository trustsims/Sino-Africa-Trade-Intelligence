import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, database


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or upgrade the SQLite database.")
    parser.add_argument("--db", help="Database path (default: database/trade_intelligence.db or TRADE_DB_PATH)")
    args = parser.parse_args()
    config.ensure_directories()
    engine = database.init_db(database.get_engine(args.db))
    ds = database.list_datasets(engine)
    print(f"Database ready: {database.database_file(engine)}")
    print(f"Schema version: {database.schema_version(engine)}")
    print(f"Datasets stored: {len(ds)}")
    if ds.empty:
        print("Next step: python scripts\\import_data.py  (imports comtrade_zambia_china_exports.csv)")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
