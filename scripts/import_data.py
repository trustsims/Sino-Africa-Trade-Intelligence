import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, database
from src import data_ingestion as di


def find_primary() -> Path | None:
    for p in (config.RAW_DIR / config.PRIMARY_DATASET_NAME, config.PROJECT_ROOT / config.PRIMARY_DATASET_NAME, config.DATA_DIR / config.PRIMARY_DATASET_NAME):
        if p.exists():
            return p
    return None


def report(out: dict) -> None:
    print(out["message"])
    if "summary" in out:
        sm = out["summary"]
        print(f"  rows read {sm['raw_rows']}, valid {sm['clean_rows']}, excluded {sm['excluded_rows']}, years {sm['year_min']}-{sm['year_max']}")
        print(f"  perspective: {sm['perspective']}; HS levels {sm['hs_levels']}; classifications {sm['classifications']}")
        for chk in sm.get("dataset_checks", []):
            print(f"  [{chk['severity']}] {chk['check']}: {chk['message']}")
        for rc in sm.get("rule_counts", []):
            print(f"  rule {rc['rule']} ({rc['severity']}): {rc['issue']} x{rc['rows']}")
    overlap = out.get("overlap")
    if overlap is not None and len(overlap):
        print("  note: records overlap with existing datasets; only the latest copy is used in analyses")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a trade dataset (CSV/Excel) into the database. The source file is never modified.")
    parser.add_argument("path", nargs="?", help=f"File to import (default: {config.PRIMARY_DATASET_NAME} in data/raw or the project root)")
    parser.add_argument("--name", help="Dataset name")
    parser.add_argument("--sheet", help="Excel worksheet name")
    parser.add_argument("--demo", action="store_true", help="Import the clearly labelled SYNTHETIC demonstration dataset")
    parser.add_argument("--synthetic", action="store_true", help="Mark the imported file as synthetic data")
    args = parser.parse_args()
    engine = database.init_db(database.get_engine())
    if args.demo:
        if not config.SYNTHETIC_SAMPLE_FILE.exists():
            from scripts.generate_synthetic_demo import generate

            generate().to_csv(config.SYNTHETIC_SAMPLE_FILE, index=False)
        out = di.import_file(engine, config.SYNTHETIC_SAMPLE_FILE, dataset_name="SYNTHETIC demo – Zambia/China mirror", is_synthetic=True)
        report(out)
        print("WARNING: synthetic data are not real trade statistics.")
        return 0
    path = Path(args.path) if args.path else find_primary()
    if path is None:
        print(f"Could not find {config.PRIMARY_DATASET_NAME}. Copy it to data/raw/ or the project root, or pass its path:")
        print("  python scripts\\import_data.py path\\to\\file.csv")
        print("No sample data was substituted.")
        return 1
    try:
        out = di.import_file(engine, path, dataset_name=args.name, is_synthetic=args.synthetic, sheet=args.sheet)
    except di.IngestionError as exc:
        print(f"Import failed: {exc}")
        return 1
    except Exception as exc:
        print(f"Import failed and was rolled back: {exc}")
        return 1
    report(out)
    return 0 if out["status"] in ("imported", "duplicate") else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
