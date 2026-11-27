import numpy as np
import pandas as pd

from src.schema import country_name
from src.trade_analytics import product_label

DIRECTIONS = {
    "exports": ("X", "M", "{a}-reported exports to {b} vs {b}-reported imports from {a}"),
    "imports": ("M", "X", "{a}-reported imports from {b} vs {b}-reported exports to {a}"),
}

CAUSES = [
    (
        "FOB versus CIF valuation",
        "Exporters normally value goods free on board (FOB); importers value them including cost, insurance and freight (CIF). Mirror import values are therefore expected to exceed export values by the cost of freight and insurance.",
    ),
    ("Reporting period differences", "Goods shipped late in one year may be recorded by the importer in the following year, shifting values between years."),
    ("Shipping and customs timing", "Long transit times, especially for land-locked exporters using regional ports, separate the export and import declaration dates."),
    (
        "Re-exports and country of origin",
        "Importers attribute goods to the country of origin, while exporters attribute them to the country of last known destination; goods routed through third countries or traders can appear under different partners.",
    ),
    ("Product classification differences", "The two customs authorities may classify the same shipment under different HS codes or HS versions."),
    ("Partner-country attribution", "Goods may be declared to an intermediate or final destination differently by the two sides (for example via Hong Kong SAR or transit hubs)."),
    (
        "Currency conversion and data revisions",
        "National values are converted to US dollars with different exchange rates and dates, and either side may revise data after first publication.",
    ),
    ("Missing or incomplete records", "Confidential, suppressed or late-reported records create apparent gaps that are not genuine absences of trade."),
]


def mirror_compare(df: pd.DataFrame, a: str, b: str, level: int, direction: str = "exports") -> dict:
    fa, fb, template = DIRECTIONS[direction]
    name_a, name_b = country_name(a), country_name(b)
    title = template.format(a=name_a, b=name_b)
    result = {"title": title, "a_label": f"{name_a}-reported", "b_label": f"{name_b}-reported", "status": "ok", "message": None}
    side_a = df[(df["reporter_code"] == a) & (df["partner_code"] == b) & (df["flow"] == fa) & (df["hs_level"] == level)]
    side_b = df[(df["reporter_code"] == b) & (df["partner_code"] == a) & (df["flow"] == fb) & (df["hs_level"] == level)]
    if side_a.empty or side_b.empty:
        missing = []
        if side_a.empty:
            missing.append(f"{name_a} as reporter ({'exports' if fa == 'X' else 'imports'}, partner {name_b})")
        if side_b.empty:
            missing.append(f"{name_b} as reporter ({'imports' if fb == 'M' else 'exports'}, partner {name_a})")
        result.update(
            status="insufficient",
            message="A valid mirror comparison cannot be calculated yet. Missing data for: "
            + "; ".join(missing)
            + ". Import the missing reporter's dataset on the Data Management page. "
            "Missing partner observations are never estimated or invented.",
        )
        return result
    keys = ["period", "year", "classification", "hs_code"]
    desc = pd.concat([side_a, side_b]).dropna(subset=["product_description"]).groupby("hs_code")["product_description"].first()
    ga = side_a.groupby(keys, as_index=False)["trade_value"].sum().rename(columns={"trade_value": "value_a"})
    gb = side_b.groupby(keys, as_index=False)["trade_value"].sum().rename(columns={"trade_value": "value_b"})
    m = ga.merge(gb, on=keys, how="outer", indicator=True)
    status = m["_merge"].map({"both": "matched", "left_only": f"{name_a} only", "right_only": f"{name_b} only"}).astype(object)
    a_codes = set(zip(ga["period"], ga["hs_code"], ga["classification"]))
    b_codes = set(zip(gb["period"], gb["hs_code"], gb["classification"]))
    a_pc = {(p, c) for p, c, _ in a_codes}
    b_pc = {(p, c) for p, c, _ in b_codes}
    for i, row in m[m["_merge"] != "both"].iterrows():
        other = b_pc if row["_merge"] == "left_only" else a_pc
        if (row["period"], row["hs_code"]) in other:
            status.loc[i] = "incomparable (classification version differs)"
    m["match_status"] = status
    m = m.drop(columns="_merge")
    matched = m["match_status"] == "matched"
    m["abs_discrepancy"] = np.where(matched, m["value_b"] - m["value_a"], np.nan)
    nonzero = matched & (m["value_a"] != 0)
    m["pct_discrepancy"] = np.where(nonzero, (m["value_b"] - m["value_a"]) / m["value_a"].where(nonzero) * 100, np.nan)
    m["mirror_ratio"] = np.where(nonzero, m["value_b"] / m["value_a"].where(nonzero), np.nan)
    m["product"] = [product_label(c, desc.get(c)) if c != "TOTAL" else "TOTAL – All commodities" for c in m["hs_code"]]
    m = m.sort_values(["year", "period", "hs_code"]).reset_index(drop=True)
    result["records"] = m
    result["annual"] = annual_discrepancy(m)
    result["by_product"] = product_discrepancy(m)
    result["summary"] = summary(m)
    zero_den = int((matched & (m["value_a"] == 0)).sum())
    if zero_den:
        result["message"] = f"{zero_den} matched records have a zero {name_a}-reported value; their percentage discrepancy is shown as unavailable."
    return result


def annual_discrepancy(m: pd.DataFrame) -> pd.DataFrame:
    mm = m[m["match_status"] == "matched"]
    if mm.empty:
        return pd.DataFrame(columns=["year", "value_a", "value_b", "abs_discrepancy", "pct_discrepancy", "mirror_ratio", "matched_records", "unmatched_records"])
    g = mm.groupby("year").agg(value_a=("value_a", "sum"), value_b=("value_b", "sum"), matched_records=("hs_code", "size")).reset_index()
    g["abs_discrepancy"] = g["value_b"] - g["value_a"]
    g["pct_discrepancy"] = np.where(g["value_a"] != 0, g["abs_discrepancy"] / g["value_a"].where(g["value_a"] != 0) * 100, np.nan)
    g["mirror_ratio"] = np.where(g["value_a"] != 0, g["value_b"] / g["value_a"].where(g["value_a"] != 0), np.nan)
    un = m[m["match_status"] != "matched"].groupby("year").size()
    g["unmatched_records"] = g["year"].map(un).fillna(0).astype(int)
    return g


def product_discrepancy(m: pd.DataFrame) -> pd.DataFrame:
    mm = m[m["match_status"] == "matched"]
    if mm.empty:
        return pd.DataFrame(columns=["hs_code", "product", "value_a", "value_b", "abs_discrepancy", "pct_discrepancy", "years_matched"])
    g = mm.groupby(["hs_code", "product"]).agg(value_a=("value_a", "sum"), value_b=("value_b", "sum"), years_matched=("year", "nunique")).reset_index()
    g["abs_discrepancy"] = g["value_b"] - g["value_a"]
    g["pct_discrepancy"] = np.where(g["value_a"] != 0, g["abs_discrepancy"] / g["value_a"].where(g["value_a"] != 0) * 100, np.nan)
    return g.reindex(g["abs_discrepancy"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def summary(m: pd.DataFrame) -> dict:
    total = len(m)
    matched = m[m["match_status"] == "matched"]
    a_total = m["value_a"].sum(skipna=True)
    pct = matched["pct_discrepancy"].dropna()
    return {
        "records_total": int(total),
        "records_matched": int(len(matched)),
        "match_rate_pct": len(matched) / total * 100 if total else np.nan,
        "value_coverage_pct": float(matched["value_a"].sum() / a_total * 100) if a_total else np.nan,
        "a_only": int((m["value_a"].notna() & m["value_b"].isna() & ~m["match_status"].str.startswith("incomparable")).sum()),
        "b_only": int((m["value_a"].isna() & m["value_b"].notna() & ~m["match_status"].str.startswith("incomparable")).sum()),
        "incomparable": int(m["match_status"].str.startswith("incomparable").sum()),
        "total_a_matched": float(matched["value_a"].sum()),
        "total_b_matched": float(matched["value_b"].sum()),
        "aggregate_pct_discrepancy": float((matched["value_b"].sum() - matched["value_a"].sum()) / matched["value_a"].sum() * 100) if matched["value_a"].sum() else np.nan,
        "median_pct_discrepancy": float(pct.median()) if len(pct) else np.nan,
        "share_within_10pct": float((pct.abs() <= 10).mean() * 100) if len(pct) else np.nan,
        "undefined_pct": int(matched["pct_discrepancy"].isna().sum()),
    }
