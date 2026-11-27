from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import forecasting as fcst
from src.config import COPPER_RELATED_PREFIXES
from src.schema import ForecastConfig

ZAMBIA, CHINA = "894", "156"

SERIES = {
    "copper": ("Copper-related exports to China (Zambia-reported)", ZAMBIA, CHINA, "X", True),
    "exports": ("Total exports to China (Zambia-reported)", ZAMBIA, CHINA, "X", False),
    "imports": ("Imports from China (Zambia-reported)", ZAMBIA, CHINA, "M", False),
    "china_imports": ("Imports from Zambia (China-reported)", CHINA, ZAMBIA, "M", False),
}

PRODUCTION_REFERENCE = {
    "base_year": 2024,
    "base_production_t": 825_271.0,
    "base_source": "Ministry of Mines and Minerals Development figure reported by SMM (2026)",
    "start_year": 2025,
    "start_production_t": 890_346.0,
    "start_source": "Reuters (2026)",
}

DEFAULT_SCENARIOS = [
    {"scenario": "S1 Production stays at the 2025 level", "target_t": 890_346.0, "target_year": 2025},
    {"scenario": "S2 Strategy partly achieved (2 Mt by 2034)", "target_t": 2_000_000.0, "target_year": 2034},
    {"scenario": "S3 Strategy achieved (3 Mt by 2031)", "target_t": 3_000_000.0, "target_year": 2031},
]

DISCLAIMER = (
    "Long-range projections are conditional calculations, not predictions of what will happen. Statistical projections assume the past "
    "behaviour of each series continues; scenarios assume the stated production path, the base-year share sent to China and the base-year "
    "unit value within the chosen price band. Their purpose is to show which forces matter, not to give exact values."
)


@dataclass
class BaseInputs:
    year: int
    value: float
    tonnes: float
    value_coverage_pct: float
    unit_value: float
    share: float


def best_level(df: pd.DataFrame) -> int | None:
    levels = sorted({int(x) for x in df["hs_level"].unique() if int(x) >= 4}, reverse=True)
    return levels[0] if levels else None


def select(df: pd.DataFrame, reporter: str, partner: str, flow: str, level: int) -> pd.DataFrame:
    return df[(df["reporter_code"] == reporter) & (df["partner_code"] == partner) & (df["flow"] == flow) & (df["hs_level"] == level)]


def copper_rows(df: pd.DataFrame, level: int) -> pd.DataFrame:
    sub = select(df, ZAMBIA, CHINA, "X", level)
    return sub[sub["hs_code"].str.startswith(COPPER_RELATED_PREFIXES)]


def build_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    level = best_level(df)
    out = {}
    for key, (_, rep, par, flow, copper) in SERIES.items():
        if copper:
            if level is None:
                continue
            sub = copper_rows(df, level)
        else:
            sub = select(df, rep, par, flow, 0)
        if not sub.empty:
            out[key] = fcst.build_series(sub, "A")
    return out


def milestones(last_year: int, horizon: int) -> list[int]:
    marks = [y for y in (last_year + 5, last_year + 10) if y <= last_year + horizon]
    return marks or [last_year + horizon]


def project(series: dict[str, pd.Series], horizon: int, interval: int, min_train: int = 5, tolerance: float = 5.0) -> dict[str, dict]:
    cfg = ForecastConfig(horizon=horizon, interval_level=interval, min_train=min_train, parsimony_tolerance_pct=tolerance)
    return {k: fcst.run_forecast(s, "A", cfg) for k, s in series.items()}


def projection_table(results: dict[str, dict], years: list[int]) -> pd.DataFrame:
    rows = []
    for key, res in results.items():
        if res.get("status") in ("insufficient", "failed"):
            continue
        fc = res["forecasts"]
        mase = res["metrics"].set_index("model")["MASE"] if not res["metrics"].empty else pd.Series(dtype=float)
        row = {"key": key, "series": SERIES[key][0], "model": res["selected"], "mase": float(mase.get(res["selected"], np.nan))}
        for y in years:
            sel = fc[(fc["model"] == res["selected"]) & (fc["period"] == str(y))]
            allm = fc[fc["period"] == str(y)]
            if sel.empty:
                continue
            row[f"{y}"] = float(sel["forecast"].iloc[0])
            row[f"{y} lower"] = float(sel["lower"].iloc[0])
            row[f"{y} upper"] = float(sel["upper"].iloc[0])
            row[f"{y} min of models"] = float(allm["forecast"].min())
            row[f"{y} max of models"] = float(allm["forecast"].max())
        rows.append(row)
    return pd.DataFrame(rows)


def balance_paths(results: dict[str, dict]) -> pd.DataFrame:
    if "exports" not in results or "imports" not in results:
        return pd.DataFrame()
    ex, im = results["exports"], results["imports"]
    if any(r.get("status") in ("insufficient", "failed") for r in (ex, im)):
        return pd.DataFrame()
    out = []
    for label, pick in (("Selected models", None), ("Linear trends", "Linear trend")):
        ef = ex["forecasts"][ex["forecasts"]["model"] == (pick or ex["selected"])].set_index("period")["forecast"]
        mf = im["forecasts"][im["forecasts"]["model"] == (pick or im["selected"])].set_index("period")["forecast"]
        joined = (ef - mf).dropna()
        for p, v in joined.items():
            out.append({"basis": label, "year": int(p), "balance": float(v)})
    return pd.DataFrame(out)


def base_inputs(df: pd.DataFrame, base_year: int, national_production_t: float) -> BaseInputs | None:
    level = best_level(df)
    if level is None:
        return None
    cu = copper_rows(df, level)
    cu = cu[cu["year"] == base_year]
    if cu.empty:
        return None
    value = float(cu["trade_value"].sum())
    weighed = cu[cu["net_weight_kg"].notna() & (cu["net_weight_kg"] > 0)]
    if weighed.empty:
        return None
    tonnes = float(weighed["net_weight_kg"].sum()) / 1000.0
    uv = float(weighed["trade_value"].sum()) / tonnes
    tonnes_total = value / uv
    coverage = float(weighed["trade_value"].sum()) / value * 100.0 if value else np.nan
    share = tonnes_total / national_production_t if national_production_t > 0 else np.nan
    return BaseInputs(base_year, value, tonnes_total, coverage, uv, share)


def production_path(start_year: int, start_t: float, target_t: float, target_year: int, end_year: int) -> pd.Series:
    years = list(range(start_year, end_year + 1))
    span = max(target_year - start_year, 0)
    vals = []
    for y in years:
        if span == 0 or y >= target_year:
            vals.append(target_t if y >= target_year else start_t)
        else:
            vals.append(start_t + (target_t - start_t) * (y - start_year) / span)
    return pd.Series(vals, index=years, dtype=float)


def scenario_frame(scenarios: list[dict], inputs: BaseInputs, start_year: int, start_t: float, end_year: int, band_pct: float) -> pd.DataFrame:
    rows = []
    for sc in scenarios:
        path = production_path(start_year, start_t, float(sc["target_t"]), int(sc["target_year"]), end_year)
        for y, prod in path.items():
            china_t = prod * inputs.share
            v = china_t * inputs.unit_value
            rows.append(
                {
                    "scenario": sc["scenario"],
                    "year": int(y),
                    "production_t": prod,
                    "to_china_t": china_t,
                    "value": v,
                    "low": v * (1 - band_pct / 100.0),
                    "high": v * (1 + band_pct / 100.0),
                }
            )
    return pd.DataFrame(rows)


def required_growth(start_t: float, start_year: int, target_t: float, target_year: int) -> float:
    n = target_year - start_year
    if target_t == start_t and start_t > 0:
        return 0.0
    if n <= 0 or start_t <= 0 or target_t <= 0:
        return float("nan")
    return ((target_t / start_t) ** (1 / n) - 1) * 100.0


def nearest_scenario(frame: pd.DataFrame, observed: pd.Series) -> pd.DataFrame:
    common = sorted(set(observed.index.astype(int)) & set(frame["year"]))
    if not common:
        return pd.DataFrame()
    rows = []
    for name, g in frame.groupby("scenario", sort=False):
        g = g.set_index("year")
        err = [abs(float(observed.loc[y]) - float(g.loc[y, "value"])) for y in common]
        rows.append({"scenario": name, "years_compared": len(common), "mean_abs_gap": float(np.mean(err))})
    return pd.DataFrame(rows).sort_values("mean_abs_gap")
