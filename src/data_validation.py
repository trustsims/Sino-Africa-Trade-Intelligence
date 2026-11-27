from datetime import date

import pandas as pd

from src import config

RULES = {
    "V01": ("Missing year", "error", "Row excluded from analysis"),
    "V02": ("Year outside valid range", "error", "Row excluded from analysis"),
    "V03": ("Missing trade value", "error", "Row excluded; missing values are never converted to zero"),
    "V04": ("Non-numeric trade value", "error", "Row excluded from analysis"),
    "V05": ("Negative trade value", "error", "Row excluded from analysis"),
    "V06": ("Invalid commodity code", "error", "Row excluded from analysis"),
    "V07": ("Commodity code lost leading zero", "info", "Code left-padded with '0' (e.g. 10121 -> 010121)"),
    "V08": ("Missing or unrecognised trade flow", "error", "Row excluded from analysis"),
    "V09": ("Missing reporter or partner", "error", "Row excluded from analysis"),
    "V10": ("Invalid month for monthly record", "error", "Row excluded from analysis"),
    "V11": ("Exact duplicate record", "warning", "First occurrence kept, later copies excluded"),
    "V12": ("Conflicting duplicate (same key, different values)", "error", "All conflicting rows excluded for manual review"),
    "V13": ("Breakdown row (transport mode / customs procedure / second partner)", "info", "Excluded because an aggregate row for the same record exists (avoids double counting)"),
    "V14": ("Non-numeric net weight or quantity", "warning", "Weight/quantity set to unavailable; trade value kept"),
    "V15": ("Negative net weight or quantity", "warning", "Weight/quantity set to unavailable; trade value kept"),
}

DATASET_CHECKS = {
    "D01": "Multiple currencies in dataset",
    "D02": "Inconsistent quantity units for the same commodity",
    "D03": "Multiple classification versions in dataset",
    "D04": "Annual and monthly records mixed in one dataset",
    "D05": "Missing optional fields",
    "D06": "Aggregate TOTAL rows present",
    "D07": "Zero-valued records",
    "D08": "Gaps in the year sequence",
    "D09": "Currency not supplied by source",
    "D10": "Valuation basis inferred from trade flow",
}


def issue(row: int, field: str, value, rule: str) -> dict:
    label, severity, action = RULES[rule]
    return {"row": int(row) + 1, "field": field, "value": None if value is None else str(value)[:80], "rule": rule, "issue": label, "severity": severity, "action": action}


def _emit(out: list, mask: pd.Series, field: str, values: pd.Series | None, rule: str) -> None:
    for idx in mask[mask].index:
        out.append(issue(idx, field, None if values is None else values.loc[idx], rule))


def _blank(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().isin(["", "nan", "None", "NaN"])


def row_issues(canon: pd.DataFrame, raw_value: pd.Series, raw_hs: pd.Series, padded: pd.Series) -> pd.DataFrame:
    max_year = date.today().year
    out: list[dict] = []
    year = canon["year"]
    _emit(out, year.isna(), "year", None, "V01")
    _emit(out, year.notna() & ((year < config.MIN_VALID_YEAR) | (year > max_year)), "year", year, "V02")
    blank_value = _blank(raw_value)
    val = canon["trade_value"]
    _emit(out, blank_value, "trade_value", None, "V03")
    _emit(out, ~blank_value & val.isna(), "trade_value", raw_value, "V04")
    _emit(out, val.notna() & (val < 0), "trade_value", val, "V05")
    _emit(out, canon["hs_code"].isna(), "hs_code", raw_hs, "V06")
    _emit(out, canon["hs_code"].notna() & padded.astype(bool), "hs_code", raw_hs, "V07")
    _emit(out, canon["flow"].isna(), "flow", canon["flow_raw"], "V08")
    rp = canon["reporter_code"].isna() | canon["partner_code"].isna()
    _emit(out, rp, "reporter/partner", canon["reporter_code"].astype(str) + " / " + canon["partner_code"].astype(str), "V09")
    month = pd.to_numeric(canon["month"], errors="coerce")
    _emit(out, (canon["frequency"] == "M") & (month.isna() | (month < 1) | (month > 12)), "month", canon["month"], "V10")
    for f in ("net_weight_kg", "quantity"):
        raw = canon[f"{f}_raw"]
        _emit(out, ~_blank(raw) & canon[f].isna(), f, raw, "V14")
        _emit(out, canon[f].notna() & (canon[f] < 0), f, canon[f], "V15")
    cols = ["row", "field", "value", "rule", "issue", "severity", "action"]
    df = pd.DataFrame(out, columns=cols)
    return df.sort_values(["row", "rule"], kind="stable").reset_index(drop=True) if not df.empty else df


def duplicate_issues(canon: pd.DataFrame, valid_mask: pd.Series) -> tuple[pd.DataFrame, pd.Index]:
    v = canon[valid_mask]
    out = []
    drop = []
    if v.empty:
        return pd.DataFrame(out, columns=["row", "field", "value", "rule", "issue", "severity", "action"]), pd.Index(drop)
    for _, grp in v.groupby("record_key", sort=False):
        if len(grp) < 2:
            continue
        if len(grp[["trade_value", "net_weight_kg", "quantity"]].round(6).drop_duplicates()) == 1:
            for idx in grp.index[1:]:
                out.append(issue(idx, "record", grp.loc[idx, "record_key"], "V11"))
                drop.append(idx)
        else:
            for idx in grp.index:
                out.append(issue(idx, "record", grp.loc[idx, "record_key"], "V12"))
                drop.append(idx)
    return pd.DataFrame(out, columns=["row", "field", "value", "rule", "issue", "severity", "action"]), pd.Index(drop)


def breakdown_issues(canon: pd.DataFrame, valid_mask: pd.Series) -> tuple[pd.DataFrame, pd.Index]:
    cols = ["row", "field", "value", "rule", "issue", "severity", "action"]
    if not any(c in canon.columns and canon[c].notna().any() for c in ("mot_code", "customs_code", "partner2_code")):
        return pd.DataFrame([], columns=cols), pd.Index([])
    v = canon[valid_mask]

    def is_agg(series: pd.Series, agg_values: set) -> pd.Series:
        s = series.astype(str).str.strip().str.upper()
        return series.isna() | s.isin(agg_values)

    agg = is_agg(v["mot_code"], {"0", "", "NAN", "NONE"}) & is_agg(v["customs_code"], {"C00", "", "NAN", "NONE"}) & is_agg(v["partner2_code"], {"0", "", "NAN", "NONE"})
    agg_keys = set(v.loc[agg, "base_key"])
    breakdown = v[~agg & v["base_key"].isin(agg_keys)]
    out = [issue(idx, "breakdown", f"mot={r.mot_code}, customs={r.customs_code}, partner2={r.partner2_code}", "V13") for idx, r in breakdown.iterrows()]
    return pd.DataFrame(out, columns=cols), breakdown.index


def dataset_checks(clean: pd.DataFrame, mapping_columns: dict, constants: dict) -> list[dict]:
    checks = []
    if clean.empty:
        return checks
    currencies = sorted(clean["currency"].dropna().unique())
    if len(currencies) > 1:
        checks.append(
            {
                "check": "D01",
                "severity": "warning",
                "message": f"{DATASET_CHECKS['D01']}: {', '.join(currencies)}. Analyses filter by one currency at a time; values are never summed across currencies.",
            }
        )
    if "currency" not in mapping_columns:
        checks.append(
            {"check": "D09", "severity": "info", "message": f"{DATASET_CHECKS['D09']}; constant '{constants.get('currency', 'USD')}' applied as documented in the column mapping."}
        )
    units = clean.dropna(subset=["quantity_unit"]).groupby(["classification", "hs_code"])["quantity_unit"].nunique()
    bad_units = units[units > 1]
    if len(bad_units):
        checks.append(
            {"check": "D02", "severity": "warning", "message": f"{DATASET_CHECKS['D02']}: {len(bad_units)} commodity codes. Quantities are not converted or summed across units."}
        )
    cls = sorted(clean["classification"].dropna().unique())
    if len(cls) > 1:
        checks.append(
            {
                "check": "D03",
                "severity": "warning",
                "message": f"{DATASET_CHECKS['D03']}: {', '.join(cls)}. Codes from different versions are treated as distinct products unless an explicit mapping is recorded.",
            }
        )
    if clean["frequency"].nunique() > 1:
        checks.append({"check": "D04", "severity": "warning", "message": f"{DATASET_CHECKS['D04']}. Annual and monthly series are analysed separately."})
    missing = {c: int(clean[c].isna().sum()) for c in ("net_weight_kg", "quantity", "product_description") if clean[c].isna().any()}
    if missing:
        checks.append({"check": "D05", "severity": "info", "message": f"{DATASET_CHECKS['D05']}: " + ", ".join(f"{k} missing in {v} rows" for k, v in missing.items())})
    n_total = int((clean["hs_level"] == 0).sum())
    if n_total:
        checks.append(
            {
                "check": "D06",
                "severity": "info",
                "message": f"{DATASET_CHECKS['D06']} ({n_total} rows). They are used for coverage reconciliation and excluded from product-level sums.",
            }
        )
    zeros = int((clean["trade_value"] == 0).sum())
    if zeros:
        checks.append({"check": "D07", "severity": "info", "message": f"{DATASET_CHECKS['D07']}: {zeros} rows report a value of exactly zero (kept as reported)."})
    years = sorted(clean["year"].dropna().astype(int).unique())
    if years:
        gaps = sorted(set(range(years[0], years[-1] + 1)) - set(years))
        if gaps:
            checks.append(
                {
                    "check": "D08",
                    "severity": "warning",
                    "message": f"{DATASET_CHECKS['D08']}: no records for {', '.join(map(str, gaps))}. Missing years are not treated as zero trade.",
                }
            )
    assumed = int(clean["valuation_assumed"].sum())
    if assumed:
        checks.append(
            {
                "check": "D10",
                "severity": "info",
                "message": f"{DATASET_CHECKS['D10']} for {assumed} rows (exports FOB, imports CIF, following the UN IMTS convention used by Comtrade).",
            }
        )
    return checks
