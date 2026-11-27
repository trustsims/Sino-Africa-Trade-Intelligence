import re

import numpy as np
import pandas as pd

from src import config
from src.data_validation import breakdown_issues, dataset_checks, duplicate_issues, row_issues
from src.schema import ColumnMapping, country_name, hs_section, normalize_country_code, normalize_flow

CLEANING_RULES = [
    (
        "C01",
        "Column mapping",
        "Source columns are renamed to the canonical schema using the stored, user-confirmed mapping; unmapped optional fields stay empty or take an explicit constant.",
    ),
    ("C02", "Type conversion", "Years, months and values are parsed as numbers; thousands separators are removed. Unparseable values are flagged, never coerced to zero."),
    ("C03", "Commodity codes", "Codes are kept as text. Numeric codes with an odd number of digits (lost leading zero) are left-padded; 'TOTAL'/'ALL' become TOTAL (level 0)."),
    ("C04", "Trade flow", "Flow labels and codes are standardised to X (export), M (import), RX (re-export), RM (re-import)."),
    ("C05", "Countries", "Reporter/partner names, ISO3 codes or numeric M49 codes are standardised to M49 codes."),
    ("C06", "Valuation basis", "If not supplied, exports/re-exports are labelled FOB and imports/re-imports CIF (UN IMTS convention), and the record is marked as assumed."),
    ("C07", "Exclusion of invalid rows", "Rows failing error-level checks (V01-V06, V08-V10, V12) are excluded from analysis but kept in the raw table and issue report."),
    ("C08", "Duplicates", "Exact duplicates keep their first occurrence; conflicting duplicates are all excluded for review."),
    ("C09", "Breakdown rows", "Rows split by transport mode, customs procedure or second partner are excluded when the aggregate row for the same record exists."),
    ("C10", "Raw preservation", "Every uploaded row is stored unchanged in raw_records, and the uploaded file is copied to data/raw/uploads; the original file is never modified."),
]


def _text(series: pd.Series) -> pd.Series:
    s = series.astype(object).where(series.notna(), None)
    return s.map(lambda v: None if v is None or str(v).strip() in ("", "nan", "NaN", "None") else str(v).strip())


def _num(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(",", "", regex=False).str.replace(" ", "", regex=False).str.strip()
    s = s.where(~s.isin(["", "nan", "NaN", "None", "<NA>"]))
    return pd.to_numeric(s, errors="coerce")


def normalize_hs(value) -> tuple[str | None, bool]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None, False
    s = str(value).strip().upper()
    if s.endswith(".0"):
        s = s[:-2]
    if s in ("TOTAL", "ALL", "TOT", "TOTAL - ALL COMMODITIES"):
        return "TOTAL", False
    if not re.fullmatch(r"\d{1,10}", s):
        return None, False
    if len(s) % 2 == 1:
        return "0" + s, True
    return s, False


def _column(raw: pd.DataFrame, mapping: ColumnMapping, field: str) -> pd.Series:
    col = mapping.columns.get(field)
    if col and col in raw.columns:
        return raw[col]
    const = mapping.constants.get(field)
    return pd.Series([const] * len(raw), index=raw.index, dtype=object)


def canonicalize(raw: pd.DataFrame, mapping: ColumnMapping, source_label: str) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    c = pd.DataFrame(index=raw.index)
    period_raw = _text(_column(raw, mapping, "period"))
    year = _num(_column(raw, mapping, "year")) if "year" in mapping.columns else _num(period_raw.str[:4])
    c["year"] = year.where(year.isna() | (year == year.round()))
    month = _num(_column(raw, mapping, "month"))
    if month.isna().all() and period_raw.notna().any():
        month = _num(period_raw.where(period_raw.str.len() == 6).str[4:6])
    month = month.where(~month.isin([0, 52]))
    freq_raw = _text(_column(raw, mapping, "frequency")).str.upper()
    freq = freq_raw.where(freq_raw.isin(["A", "M"]))
    c["frequency"] = freq.fillna(pd.Series(np.where(month.notna(), "M", "A"), index=raw.index))
    c["month"] = month.where(c["frequency"] == "M")
    yr = c["year"].astype("Int64").astype(str)
    mo = c["month"].astype("Int64").astype(str).str.zfill(2)
    c["period"] = np.where(c["frequency"] == "M", yr + mo, yr)
    hs_raw = _column(raw, mapping, "hs_code")
    if "hs_code" not in mapping.columns:
        hs_raw = pd.Series(["TOTAL"] * len(raw), index=raw.index, dtype=object)
    parsed = hs_raw.map(normalize_hs)
    c["hs_code"] = parsed.map(lambda t: t[0])
    padded = parsed.map(lambda t: t[1])
    c["hs_level"] = c["hs_code"].map(lambda v: 0 if v == "TOTAL" else (len(v) if isinstance(v, str) else np.nan))
    c["chapter"] = c["hs_code"].map(lambda v: v[:2] if isinstance(v, str) and v != "TOTAL" else None)
    c["section"] = c["chapter"].map(hs_section)
    cls = _text(_column(raw, mapping, "classification"))
    c["classification"] = cls.fillna("HS").str.upper()
    c["product_description"] = _text(_column(raw, mapping, "product_description"))
    c.loc[c["hs_code"] == "TOTAL", "product_description"] = c.loc[c["hs_code"] == "TOTAL", "product_description"].fillna("All commodities")
    value_raw = _column(raw, mapping, "trade_value")
    c["trade_value"] = _num(value_raw)
    cur = _text(_column(raw, mapping, "currency"))
    c["currency"] = cur.fillna(mapping.constants.get("currency", "USD")).str.upper().str[:3]
    c["flow_raw"] = _text(_column(raw, mapping, "flow"))
    c["flow"] = c["flow_raw"].map(normalize_flow)
    for side in ("reporter", "partner"):
        code = _column(raw, mapping, f"{side}_code").map(normalize_country_code)
        name = _text(_column(raw, mapping, f"{side}_name"))
        code = code.fillna(name.map(normalize_country_code))
        c[f"{side}_code"] = code
        c[f"{side}_name"] = [country_name(cd, nm) for cd, nm in zip(code, name)]
    for f in ("net_weight_kg", "quantity"):
        r = _column(raw, mapping, f)
        c[f"{f}_raw"] = _text(r)
        c[f] = _num(r)
    c["quantity_unit"] = _text(_column(raw, mapping, "quantity_unit"))
    vb = _text(_column(raw, mapping, "valuation_basis")).str.upper()
    inferred = c["flow"].map({"X": "FOB", "RX": "FOB", "M": "CIF", "RM": "CIF"})
    c["valuation_assumed"] = vb.isna() & inferred.notna()
    c["valuation_basis"] = vb.fillna(inferred)
    ds = _text(_column(raw, mapping, "data_source"))
    c["data_source"] = ds.fillna(source_label)
    c["original_record_id"] = _text(_column(raw, mapping, "original_record_id"))
    for f in ("mot_code", "customs_code", "partner2_code"):
        c[f] = _text(_column(raw, mapping, f)).map(lambda v: v[:-2] if isinstance(v, str) and v.endswith(".0") else v)
    c["base_key"] = (
        c["reporter_code"].astype(str)
        + "|"
        + c["partner_code"].astype(str)
        + "|"
        + c["flow"].astype(str)
        + "|"
        + c["period"].astype(str)
        + "|"
        + c["classification"].astype(str)
        + "|"
        + c["hs_code"].astype(str)
    )
    c["record_key"] = c["base_key"] + "|" + c["mot_code"].fillna("").astype(str) + "|" + c["customs_code"].fillna("").astype(str) + "|" + c["partner2_code"].fillna("").astype(str)
    return c, value_raw, hs_raw, padded


def run_pipeline(raw: pd.DataFrame, mapping: ColumnMapping, source_label: str) -> dict:
    canon, value_raw, hs_raw, padded = canonicalize(raw, mapping, source_label)
    issues = row_issues(canon, value_raw, hs_raw, padded)
    error_rows = set((issues.loc[issues["severity"] == "error", "row"] - 1).tolist())
    valid = ~canon.index.isin(list(error_rows))
    valid = pd.Series(valid, index=canon.index)
    dup_issues, dup_drop = duplicate_issues(canon, valid)
    valid &= ~canon.index.isin(dup_drop)
    bd_issues, bd_drop = breakdown_issues(canon, valid)
    valid &= ~canon.index.isin(bd_drop)
    all_issues = pd.concat([d for d in (issues, dup_issues, bd_issues) if not d.empty], ignore_index=True) if any(not d.empty for d in (issues, dup_issues, bd_issues)) else issues
    flags = all_issues[all_issues["severity"].isin(["info", "warning"])].groupby("row")["rule"].apply(lambda r: ",".join(sorted(set(r))))
    clean = canon[valid].copy()
    clean["quality_flags"] = (clean.index + 1).map(flags)
    for f in ("net_weight_kg", "quantity"):
        clean.loc[clean[f] < 0, f] = np.nan
    clean["year"] = clean["year"].astype(int)
    clean["hs_level"] = clean["hs_level"].astype(int)
    clean["month"] = clean["month"].astype("Int64")
    clean = clean.drop(columns=["flow_raw", "net_weight_kg_raw", "quantity_raw", "base_key", "mot_code", "customs_code", "partner2_code"])
    excluded = canon[~valid]
    checks = dataset_checks(clean, mapping.columns, mapping.constants)
    summary = build_summary(raw, clean, excluded, all_issues, checks)
    return {"clean": clean, "excluded_index": excluded.index, "issues": all_issues, "checks": checks, "summary": summary}


def build_summary(raw: pd.DataFrame, clean: pd.DataFrame, excluded: pd.DataFrame, issues: pd.DataFrame, checks: list[dict]) -> dict:
    rule_counts = issues.groupby(["rule", "issue", "severity"]).size().reset_index(name="rows").to_dict("records") if not issues.empty else []
    perspectives = []
    if not clean.empty:
        for (r, p, f), _ in clean.groupby(["reporter_code", "partner_code", "flow"]):
            perspectives.append(f"{country_name(r)} → {country_name(p)} ({f})")
    freq = sorted(clean["frequency"].unique()) if not clean.empty else []
    return {
        "pipeline_version": config.PIPELINE_VERSION,
        "raw_rows": int(len(raw)),
        "clean_rows": int(len(clean)),
        "excluded_rows": int(len(excluded)),
        "rule_counts": rule_counts,
        "dataset_checks": checks,
        "year_min": int(clean["year"].min()) if not clean.empty else None,
        "year_max": int(clean["year"].max()) if not clean.empty else None,
        "frequency": "/".join(freq) if freq else None,
        "perspective": "; ".join(perspectives) if perspectives else None,
        "hs_levels": sorted(int(x) for x in clean["hs_level"].unique()) if not clean.empty else [],
        "classifications": sorted(clean["classification"].unique()) if not clean.empty else [],
        "currencies": sorted(clean["currency"].unique()) if not clean.empty else [],
    }


def apply_classification_mappings(df: pd.DataFrame, mappings: pd.DataFrame, target: str | None) -> tuple[pd.DataFrame, dict]:
    info = {"target": target, "mapped_rows": 0, "unmapped_codes": []}
    if df.empty or target is None or mappings.empty:
        return df, info
    out = df.copy()
    m = mappings[mappings["to_classification"] == target]
    lookup = {(r.from_classification, r.from_code): r.to_code for r in m.itertuples()}
    src_mask = (out["classification"] != target) & (out["hs_level"] > 0)
    keys = list(zip(out.loc[src_mask, "classification"], out.loc[src_mask, "hs_code"]))
    new_codes = [lookup.get(k) for k in keys]
    idx = out.index[src_mask]
    mapped = pd.Series(new_codes, index=idx)
    ok = mapped.notna()
    out.loc[ok[ok].index, "hs_code"] = mapped[ok]
    out.loc[ok[ok].index, "classification"] = target
    out.loc[ok[ok].index, "chapter"] = mapped[ok].str[:2]
    out.loc[ok[ok].index, "section"] = mapped[ok].str[:2].map(hs_section)
    info["mapped_rows"] = int(ok.sum())
    info["unmapped_codes"] = sorted({f"{c}:{h}" for (c, h), v in zip(keys, new_codes) if v is None})
    return out, info
