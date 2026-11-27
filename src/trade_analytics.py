import math

import numpy as np
import pandas as pd

from src import config
from src.schema import FLOW_LABELS, country_name

LEVEL_LABELS = {0: "Total (all commodities)", 2: "HS 2-digit (chapter)", 4: "HS 4-digit (heading)", 6: "HS 6-digit (subheading)"}


def level_label(level: int) -> str:
    return LEVEL_LABELS.get(int(level), f"{int(level)}-digit national tariff line")


def dedupe_across_datasets(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if df.empty:
        return df, 0
    ordered = df.sort_values("dataset_id")
    kept = ordered.drop_duplicates("record_key", keep="last")
    return kept.sort_index(), int(len(df) - len(kept))


def available_levels(df: pd.DataFrame) -> list[int]:
    if df.empty:
        return []
    return sorted(int(x) for x in df["hs_level"].unique())


def default_level(levels: list[int]) -> int | None:
    product_levels = [lv for lv in levels if lv > 0]
    if product_levels:
        return max(product_levels)
    return levels[0] if levels else None


def at_level(df: pd.DataFrame, level: int | None) -> pd.DataFrame:
    if df.empty or level is None:
        return df.iloc[0:0]
    return df[df["hs_level"] == int(level)]


def safe_pct_change(current: float, previous: float) -> float:
    if previous is None or current is None or pd.isna(previous) or pd.isna(current) or previous == 0:
        return np.nan
    return (current - previous) / abs(previous) * 100.0


def yoy_growth(series: pd.Series) -> pd.Series:
    s = series.sort_index()
    out = pd.Series(np.nan, index=s.index, dtype=float)
    idx = list(s.index)
    for i in range(1, len(idx)):
        prev_key, key = idx[i - 1], idx[i]
        consecutive = (key - prev_key == 1) if isinstance(key, (int, np.integer)) else True
        if consecutive:
            out.loc[key] = safe_pct_change(s.loc[key], s.loc[prev_key])
    return out


def cagr(start_value: float, end_value: float, years: float) -> float:
    if years is None or years <= 0 or pd.isna(start_value) or pd.isna(end_value) or start_value <= 0 or end_value <= 0:
        return np.nan
    return (math.pow(end_value / start_value, 1.0 / years) - 1.0) * 100.0


def annual_totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year", "flow", "reporter_code", "partner_code", "trade_value", "yoy_pct"])
    g = df.groupby(["reporter_code", "partner_code", "flow", "year"], as_index=False)["trade_value"].sum()
    parts = []
    for _, grp in g.groupby(["reporter_code", "partner_code", "flow"]):
        grp = grp.sort_values("year").copy()
        grp["yoy_pct"] = yoy_growth(grp.set_index("year")["trade_value"]).values
        parts.append(grp)
    out = pd.concat(parts, ignore_index=True)
    out["series"] = [f"{country_name(r)} → {country_name(p)} ({FLOW_LABELS.get(f, f)})" for r, p, f in zip(out["reporter_code"], out["partner_code"], out["flow"])]
    return out


def period_series(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "date", "series", "trade_value"])
    g = df.groupby(["reporter_code", "partner_code", "flow", "year", "month"], as_index=False, dropna=False)["trade_value"].sum()
    g["date"] = pd.to_datetime(dict(year=g["year"], month=g["month"].fillna(1).astype(int), day=1))
    g["series"] = [f"{country_name(r)} → {country_name(p)} ({FLOW_LABELS.get(f, f)})" for r, p, f in zip(g["reporter_code"], g["partner_code"], g["flow"])]
    return g.sort_values("date")


def product_label(code: str, desc, classification: str | None = None) -> str:
    d = desc if isinstance(desc, str) and desc else "(no description)"
    prefix = f"[{classification}] " if classification else ""
    return f"{prefix}{code} – {d[:70]}"


def _multi_cls(df: pd.DataFrame) -> bool:
    return df["classification"].nunique() > 1


def product_ranking(df: pd.DataFrame, top_n: int | None = None) -> pd.DataFrame:
    cols = ["rank", "hs_code", "classification", "product", "trade_value", "share_pct", "cumulative_share_pct", "years_present"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    desc = df.dropna(subset=["product_description"]).groupby(["classification", "hs_code"])["product_description"].first()
    g = df.groupby(["classification", "hs_code"]).agg(trade_value=("trade_value", "sum"), years_present=("year", "nunique")).reset_index()
    multi = _multi_cls(df)
    g["product"] = [product_label(c, desc.get((cl, c)), cl if multi else None) for cl, c in zip(g["classification"], g["hs_code"])]
    total = g["trade_value"].sum()
    g["share_pct"] = g["trade_value"] / total * 100 if total > 0 else np.nan
    g = g.sort_values("trade_value", ascending=False).reset_index(drop=True)
    g["cumulative_share_pct"] = g["share_pct"].cumsum()
    g["rank"] = np.arange(1, len(g) + 1)
    g = g[cols]
    return g.head(top_n) if top_n else g


def product_year_matrix(df: pd.DataFrame, codes: list[str] | None = None) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    d = df if codes is None else df[df["hs_code"].isin(codes)]
    if d.empty:
        return pd.DataFrame()
    multi = _multi_cls(d)
    desc = d.dropna(subset=["product_description"]).groupby(["classification", "hs_code"])["product_description"].first()
    m = d.pivot_table(index=["classification", "hs_code"], columns="year", values="trade_value", aggfunc="sum")
    m.index = [product_label(c, desc.get((cl, c)), cl if multi else None) for cl, c in m.index]
    return m


def hhi(values) -> float:
    v = np.asarray([x for x in values if pd.notna(x) and x > 0], dtype=float)
    if v.size == 0 or v.sum() <= 0:
        return np.nan
    s = v / v.sum()
    return float(np.sum(s**2))


def normalized_hhi(h: float, n: int) -> float:
    if pd.isna(h) or n is None or n <= 1:
        return np.nan
    return (h - 1.0 / n) / (1.0 - 1.0 / n)


def concentration_ratio(values, k: int) -> float:
    v = np.sort(np.asarray([x for x in values if pd.notna(x) and x > 0], dtype=float))[::-1]
    if v.size == 0:
        return np.nan
    return float(v[:k].sum() / v.sum() * 100.0)


def concentration_by_year(df: pd.DataFrame, group_col: str = "hs_code") -> pd.DataFrame:
    cols = ["year", "products_observed", "products_ge_1pct", "hhi", "hhi_points", "normalized_hhi", "effective_products", "cr1_pct", "cr3_pct", "cr5_pct"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for (year,), grp in df.groupby(["year"]):
        keys = ["classification", group_col] if group_col == "hs_code" else [group_col]
        vals = grp.groupby(keys)["trade_value"].sum()
        vals = vals[vals > 0]
        h = hhi(vals.values)
        n = int(len(vals))
        shares = vals / vals.sum() * 100 if vals.sum() > 0 else vals
        rows.append(
            {
                "year": int(year),
                "products_observed": n,
                "products_ge_1pct": int((shares >= 1).sum()),
                "hhi": h,
                "hhi_points": h * 10000 if pd.notna(h) else np.nan,
                "normalized_hhi": normalized_hhi(h, n),
                "effective_products": 1.0 / h if pd.notna(h) and h > 0 else np.nan,
                "cr1_pct": concentration_ratio(vals.values, 1),
                "cr3_pct": concentration_ratio(vals.values, 3),
                "cr5_pct": concentration_ratio(vals.values, 5),
            }
        )
    return pd.DataFrame(rows, columns=cols).sort_values("year")


def hhi_band(points: float) -> str:
    if pd.isna(points):
        return "not available"
    if points < 1500:
        return "unconcentrated (below 1,500)"
    if points < 2500:
        return "moderately concentrated (1,500–2,500)"
    return "highly concentrated (above 2,500)"


def group_summary(df: pd.DataFrame, by: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[by, "trade_value", "share_pct", "products"])
    g = df.groupby(by).agg(trade_value=("trade_value", "sum"), products=("hs_code", "nunique")).reset_index()
    total = g["trade_value"].sum()
    g["share_pct"] = g["trade_value"] / total * 100 if total > 0 else np.nan
    return g.sort_values("trade_value", ascending=False).reset_index(drop=True)


def copper_breakdown(df: pd.DataFrame, prefixes=config.COPPER_RELATED_PREFIXES) -> dict:
    result = {"available": False, "note": None, "ore_available": False}
    if df.empty:
        result["note"] = "No records at the selected level."
        return result
    level = int(df["hs_level"].iloc[0])
    if level == 0:
        result["note"] = "Copper cannot be isolated from all-commodity totals; select an HS product level."
        return result
    usable = [p for p in prefixes if len(p) <= level]
    if not usable:
        result["note"] = "The selected HS level is too coarse to isolate copper products."
        return result
    related = pd.Series(False, index=df.index)
    for p in usable:
        related |= df["hs_code"].str.startswith(p)
    ore = df["hs_code"].str.startswith(config.COPPER_ORE_CODE[:level]) if level >= 4 else pd.Series(False, index=df.index)
    total_by_year = df.groupby("year")["trade_value"].sum()
    rel_by_year = df[related].groupby("year")["trade_value"].sum().reindex(total_by_year.index)
    ore_by_year = df[ore].groupby("year")["trade_value"].sum().reindex(total_by_year.index) if level >= 4 else None
    table = pd.DataFrame({"total": total_by_year, "copper_related": rel_by_year})
    if ore_by_year is not None:
        table["copper_ore_2603"] = ore_by_year
        table["ore_share_pct"] = np.where(table["total"] > 0, table["copper_ore_2603"] / table["total"] * 100, np.nan)
    table["related_share_pct"] = np.where(table["total"] > 0, table["copper_related"] / table["total"] * 100, np.nan)
    result.update(
        {
            "available": True,
            "ore_available": level >= 4,
            "table": table.reset_index(),
            "prefixes_used": usable,
            "level": level,
            "note": None if level >= 4 else "At HS 2-digit level only Chapter 74 (copper and articles) can be isolated; HS 2603 copper ores require 4- or 6-digit data.",
        }
    )
    return result


def reconciliation(df_all: pd.DataFrame, level: int | None) -> pd.DataFrame:
    cols = ["year", "series", "product_level_sum", "reported_total", "coverage_pct"]
    if df_all.empty or level is None or level == 0:
        return pd.DataFrame(columns=cols)
    tot = df_all[df_all["hs_level"] == 0]
    if tot.empty:
        return pd.DataFrame(columns=cols)
    keys = ["reporter_code", "partner_code", "flow", "year"]
    lv = df_all[df_all["hs_level"] == level].groupby(keys)["trade_value"].sum().rename("product_level_sum")
    tt = tot.groupby(keys)["trade_value"].sum().rename("reported_total")
    m = pd.concat([lv, tt], axis=1).reset_index()
    m["coverage_pct"] = np.where(m["reported_total"] > 0, m["product_level_sum"] / m["reported_total"] * 100, np.nan)
    m["series"] = [f"{country_name(r)} → {country_name(p)} ({f})" for r, p, f in zip(m["reporter_code"], m["partner_code"], m["flow"])]
    return m[cols].sort_values(["series", "year"])


def trade_balance(df: pd.DataFrame, reporter: str, partner: str) -> pd.DataFrame:
    d = df[(df["reporter_code"] == reporter) & (df["partner_code"] == partner)]
    if d.empty or not {"X", "M"} <= set(d["flow"].unique()):
        return pd.DataFrame(columns=["year", "exports", "imports", "balance"])
    p = d[d["flow"].isin(["X", "M"])].pivot_table(index="year", columns="flow", values="trade_value", aggfunc="sum")
    p = p.dropna(subset=["X", "M"])
    out = pd.DataFrame({"year": p.index, "exports": p["X"].values, "imports": p["M"].values})
    out["balance"] = out["exports"] - out["imports"]
    return out


def unit_values(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["hs_code", "product", "trade_value", "net_weight_kg", "usd_per_kg", "years"])
    d = df.dropna(subset=["net_weight_kg"])
    d = d[d["net_weight_kg"] > 0]
    if d.empty:
        return pd.DataFrame(columns=["hs_code", "product", "trade_value", "net_weight_kg", "usd_per_kg", "years"])
    multi = _multi_cls(d)
    desc = d.dropna(subset=["product_description"]).groupby(["classification", "hs_code"])["product_description"].first()
    g = d.groupby(["classification", "hs_code"]).agg(trade_value=("trade_value", "sum"), net_weight_kg=("net_weight_kg", "sum"), years=("year", "nunique")).reset_index()
    g["usd_per_kg"] = g["trade_value"] / g["net_weight_kg"]
    g["product"] = [product_label(c, desc.get((cl, c)), cl if multi else None) for cl, c in zip(g["classification"], g["hs_code"])]
    return g


def observations(df: pd.DataFrame, scale_label: str, scale: float) -> list[str]:
    notes = []
    if df.empty:
        return notes
    for (r, p, f), grp in df.groupby(["reporter_code", "partner_code", "flow"]):
        label = f"{country_name(r)} → {country_name(p)} {FLOW_LABELS.get(f, f).lower()}s"
        yearly = grp.groupby("year")["trade_value"].sum().sort_index()
        if len(yearly) >= 2:
            diffs = yearly.diff()
            consecutive = pd.Series(yearly.index, index=yearly.index).diff() == 1
            diffs = diffs[consecutive]
            if not diffs.empty and diffs.max() > 0:
                y = int(diffs.idxmax())
                notes.append(f"Largest annual increase in {label}: {y - 1}→{y}, +{diffs.max() / scale:,.1f} {scale_label} ({safe_pct_change(yearly[y], yearly[y - 1]):+.1f}%).")
            if not diffs.empty and diffs.min() < 0:
                y = int(diffs.idxmin())
                notes.append(f"Largest annual decline in {label}: {y - 1}→{y}, {diffs.min() / scale:,.1f} {scale_label} ({safe_pct_change(yearly[y], yearly[y - 1]):+.1f}%).")
            first, last = yearly.index.min(), yearly.index.max()
            g = cagr(yearly[first], yearly[last], last - first)
            if pd.notna(g):
                notes.append(
                    f"{label[0].upper() + label[1:]} changed from {yearly[first] / scale:,.1f} to {yearly[last] / scale:,.1f} {scale_label} "
                    f"between {first} and {last} (compound annual growth {g:+.1f}%)."
                )
        if (grp["hs_level"] > 0).any():
            rank = product_ranking(grp)
            if not rank.empty:
                top = rank.iloc[0]
                notes.append(f"Leading product in {label}: {top['product']} with {top['share_pct']:.1f}% of the selected period's value.")
            conc = concentration_by_year(grp)
            if len(conc) >= 2 and conc["hhi_points"].notna().sum() >= 2:
                c0, c1 = conc.dropna(subset=["hhi_points"]).iloc[[0, -1]].to_dict("records")
                direction = "rose" if c1["hhi_points"] > c0["hhi_points"] else "fell"
                notes.append(
                    f"Export-basket concentration (HHI) for {label} {direction} from {c0['hhi_points']:,.0f} in {c0['year']} "
                    f"to {c1['hhi_points']:,.0f} in {c1['year']} ({hhi_band(c1['hhi_points'])})."
                )
    return notes
