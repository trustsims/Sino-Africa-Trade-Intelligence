import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config

PRODUCTS = [
    ("260300", "Copper ores and concentrates", 1.0, 0.25),
    ("740311", "Refined copper; cathodes and sections of cathodes", 3.0, 0.20),
    ("740200", "Unrefined copper; copper anodes for electrolytic refining", 0.6, 0.30),
    ("810520", "Cobalt mattes and other intermediate products; unwrought cobalt", 0.15, 0.35),
    ("261690", "Precious metal ores and concentrates (excl. silver)", 0.04, 0.40),
    ("440799", "Wood sawn or chipped lengthwise, n.e.c.", 0.02, 0.30),
    ("120740", "Sesamum seeds", 0.01, 0.45),
    ("710310", "Precious and semi-precious stones, unworked", 0.008, 0.50),
    ("520100", "Cotton, not carded or combed", 0.02, 0.45),
    ("240120", "Tobacco, partly or wholly stemmed or stripped", 0.012, 0.35),
]


def generate(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    years = list(range(2015, 2025))
    rows = []
    for code, desc, scale, vol in PRODUCTS:
        level = scale * 1e9
        trend = rng.normal(0.03, 0.02)
        for i, y in enumerate(years):
            shock = rng.normal(0, vol)
            zm_value = max(level * np.exp(trend * i + shock), 0.0)
            ratio = rng.uniform(0.98, 1.18)
            if rng.random() < 0.08:
                ratio = rng.uniform(0.6, 1.6)
            cn_value = zm_value * ratio
            weight = zm_value / rng.uniform(1.5, 9.0)
            if not (code == "520100" and y in (2017, 2018)):
                rows.append(_row(894, "ZMB", "Zambia", 156, "CHN", "China", "X", "Export", y, code, desc, zm_value, weight, "FOB"))
            if not (code == "710310" and y in (2020, 2021)):
                rows.append(_row(156, "CHN", "China", 894, "ZMB", "Zambia", "M", "Import", y, code, desc, cn_value, weight * rng.uniform(0.95, 1.05), "CIF"))
    df = pd.DataFrame(rows)
    totals = []
    for (_, flow, y), grp in df.groupby(["reporterCode", "flowCode", "refYear"]):
        first = grp.iloc[0]
        unreported = grp["primaryValue"].sum() * rng.uniform(0.01, 0.04)
        totals.append(
            _row(
                first.reporterCode,
                first.reporterISO,
                first.reporterDesc,
                first.partnerCode,
                first.partnerISO,
                first.partnerDesc,
                flow,
                first.flowDesc,
                y,
                "TOTAL",
                "All Commodities",
                grp["primaryValue"].sum() + unreported,
                np.nan,
                first.valuationBasis,
            )
        )
    out = pd.concat([df, pd.DataFrame(totals)], ignore_index=True)
    out["primaryValue"] = out["primaryValue"].round(0)
    out["netWgt"] = out["netWgt"].round(0)
    return out.sort_values(["reporterCode", "refYear", "cmdCode"]).reset_index(drop=True)


def _row(rc, riso, rdesc, pc, piso, pdesc, flow, flowdesc, year, code, desc, value, weight, basis):
    return {
        "typeCode": "C",
        "freqCode": "A",
        "refYear": year,
        "refMonth": 52,
        "period": year,
        "reporterCode": rc,
        "reporterISO": riso,
        "reporterDesc": rdesc,
        "flowCode": flow,
        "flowDesc": flowdesc,
        "partnerCode": pc,
        "partnerISO": piso,
        "partnerDesc": pdesc,
        "classificationCode": "H5",
        "cmdCode": code,
        "cmdDesc": desc,
        "aggrLevel": 0 if code == "TOTAL" else 6,
        "qtyUnitAbbr": "kg",
        "netWgt": weight,
        "primaryValue": value,
        "valuationBasis": basis,
        "dataSource": "SYNTHETIC demonstration data - NOT real trade statistics",
    }


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    out = generate()
    config.SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(config.SYNTHETIC_SAMPLE_FILE, index=False)
    print(f"Wrote {len(out)} SYNTHETIC rows to {config.SYNTHETIC_SAMPLE_FILE}")
