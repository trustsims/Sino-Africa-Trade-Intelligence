import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src import config
from src import data_ingestion as di


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a trade CSV/Excel file without importing or modifying it.")
    parser.add_argument("path", nargs="?", help=f"File to inspect (default: {config.PRIMARY_DATASET_NAME})")
    args = parser.parse_args()
    candidates = [Path(args.path)] if args.path else [config.RAW_DIR / config.PRIMARY_DATASET_NAME, config.PROJECT_ROOT / config.PRIMARY_DATASET_NAME]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        print("File not found:", ", ".join(str(p) for p in candidates))
        return 1
    raw, info = di.read_table(path.name, path.read_bytes())
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    print(f"File: {path}")
    print(f"Rows: {info['rows']}  Columns: {len(info['columns'])}  Encoding: {info.get('encoding')}  Delimiter: {info.get('delimiter')!r}")
    print(f"UN Comtrade layout detected: {di.is_comtrade_layout(raw.columns)}")
    print("\nColumn profile:")
    print(di.column_profile(raw).to_string(index=False))
    mapping = di.suggest_mapping(raw.columns)
    print("\nSuggested mapping:")
    for k, v in mapping["columns"].items():
        print(f"  {k:22s} <- {v}")
    for k, v in mapping["constants"].items():
        print(f"  {k:22s} = {v} (constant)")
    try:
        res = di.preview_pipeline(raw, mapping, mapping["constants"].get("data_source", "User upload"))
    except Exception as exc:
        print(f"\nMapping needs manual review: {exc}")
        return 0
    sm = res["summary"]
    clean = res["clean"]
    print(
        f"\nValidation: {sm['clean_rows']} valid, {sm['excluded_rows']} excluded; years {sm['year_min']}-{sm['year_max']}; "
        f"levels {sm['hs_levels']}; classifications {sm['classifications']}; perspective {sm['perspective']}"
    )
    for chk in sm["dataset_checks"]:
        print(f"  [{chk['severity']}] {chk['message']}")
    if not clean.empty:
        print("\nTrade value by year and HS level (USD):")
        print(clean.pivot_table(index="year", columns="hs_level", values="trade_value", aggfunc="sum").map(lambda v: f"{v:,.0f}").to_string())
        top = clean[clean["hs_level"] == clean["hs_level"].max()].groupby(["hs_code", "product_description"])["trade_value"].sum().nlargest(10)
        print("\nTop 10 products at the most detailed level:")
        print(top.map(lambda v: f"{v:,.0f}").to_string())
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
