import hashlib
import json
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.schema import ForecastConfig

COMPLEXITY = {"Naive": 1, "Seasonal naive": 1, "Drift": 2, "Linear trend": 3, "ARIMA": 4, "SARIMA": 5}
DISCLAIMER = (
    "Forecasts are statistical estimates derived only from the historical series shown. They are not guarantees "
    "of future export performance and do not account for prices, policy changes, mine output or other drivers."
)


@dataclass
class FittedModel:
    name: str
    fitted: np.ndarray
    params: dict = field(default_factory=dict)
    forecaster: object = None

    def forecast(self, h: int, level: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self.forecaster(h, level)


def _z(level: int) -> float:
    return float(stats.norm.ppf(0.5 + level / 200.0))


def _resid_sigma(resid: np.ndarray) -> float:
    r = resid[~np.isnan(resid)]
    if r.size < 2:
        return np.nan
    return float(np.sqrt(np.mean(r**2)))


def fit_naive(y: np.ndarray, season: int = 1) -> FittedModel:
    fitted = np.concatenate([[np.nan], y[:-1]])
    sigma = _resid_sigma(y - fitted)
    last = y[-1]

    def fc(h, level):
        mean = np.repeat(last, h)
        w = _z(level) * sigma * np.sqrt(np.arange(1, h + 1)) if not np.isnan(sigma) else np.full(h, np.nan)
        return mean, mean - w, mean + w

    return FittedModel("Naive", fitted, {"last_value": float(last)}, fc)


def fit_seasonal_naive(y: np.ndarray, season: int = 12) -> FittedModel:
    m = season
    fitted = np.concatenate([np.full(m, np.nan), y[:-m]])
    sigma = _resid_sigma(y - fitted)
    n = len(y)

    def fc(h, level):
        idx = [n - m + ((i - 1) % m) for i in range(1, h + 1)]
        mean = y[idx].astype(float)
        k = np.floor((np.arange(1, h + 1) - 1) / m)
        w = _z(level) * sigma * np.sqrt(k + 1) if not np.isnan(sigma) else np.full(h, np.nan)
        return mean, mean - w, mean + w

    return FittedModel("Seasonal naive", fitted, {"season": m}, fc)


def fit_drift(y: np.ndarray, season: int = 1) -> FittedModel:
    n = len(y)
    slope = (y[-1] - y[0]) / (n - 1)
    fitted = np.concatenate([[np.nan], y[:-1] + slope])
    sigma = _resid_sigma(y - fitted)

    def fc(h, level):
        steps = np.arange(1, h + 1)
        mean = y[-1] + steps * slope
        w = _z(level) * sigma * np.sqrt(steps * (1 + steps / n)) if not np.isnan(sigma) else np.full(h, np.nan)
        return mean, mean - w, mean + w

    return FittedModel("Drift", fitted, {"slope_per_period": float(slope)}, fc)


def fit_linear(y: np.ndarray, season: int = 1) -> FittedModel:
    import statsmodels.api as sm

    n = len(y)
    t = np.arange(n, dtype=float)
    X = sm.add_constant(t)
    model = sm.OLS(y, X).fit()

    def fc(h, level):
        tf = np.arange(n, n + h, dtype=float)
        Xf = np.column_stack([np.ones(h), tf])
        sf = model.get_prediction(Xf).summary_frame(alpha=1 - level / 100)
        return sf["mean"].to_numpy(), sf["obs_ci_lower"].to_numpy(), sf["obs_ci_upper"].to_numpy()

    return FittedModel(
        "Linear trend", model.fittedvalues, {"intercept": float(model.params[0]), "slope_per_period": float(model.params[1]), "r_squared": float(model.rsquared)}, fc
    )


def _arima_grid(n: int) -> list[tuple]:
    grid = []
    for d in (0, 1):
        for p in (0, 1, 2):
            for q in (0, 1):
                k = p + q + 1
                if k <= max(1, (n - d) // 3) and not (p == 0 and q == 0 and d == 0):
                    grid.append((p, d, q))
    return grid


def fit_arima(y: np.ndarray, season: int = 1) -> FittedModel:
    from statsmodels.tsa.arima.model import ARIMA

    best = None
    for order in _arima_grid(len(y)):
        trend = "c" if order[1] == 0 else "t"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = ARIMA(y, order=order, trend=trend).fit()
            score = res.aicc if np.isfinite(res.aicc) else res.aic
            if np.isfinite(score) and (best is None or score < best[0]):
                best = (score, order, trend, res)
        except Exception:
            continue
    if best is None:
        raise ValueError("ARIMA could not be estimated on this series")
    _, order, trend, res = best

    def fc(h, level):
        f = res.get_forecast(h)
        ci = f.conf_int(alpha=1 - level / 100)
        return np.asarray(f.predicted_mean), np.asarray(ci)[:, 0], np.asarray(ci)[:, 1]

    fitted = np.asarray(res.fittedvalues, dtype=float)
    fitted[: max(order[1], 1)] = np.nan
    return FittedModel("ARIMA", fitted, {"order": list(order), "trend": trend, "aicc": float(best[0])}, fc)


def fit_sarima(y: np.ndarray, season: int = 12) -> FittedModel:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    candidates = [((0, 1, 1), (0, 1, 1)), ((1, 1, 0), (1, 1, 0)), ((1, 0, 0), (0, 1, 1)), ((0, 1, 1), (0, 1, 0))]
    best = None
    for order, sorder in candidates:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = SARIMAX(y, order=order, seasonal_order=(*sorder, season), enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
            if np.isfinite(res.aic) and (best is None or res.aic < best[0]):
                best = (res.aic, order, sorder, res)
        except Exception:
            continue
    if best is None:
        raise ValueError("SARIMA could not be estimated on this series")
    _, order, sorder, res = best

    def fc(h, level):
        f = res.get_forecast(h)
        ci = f.conf_int(alpha=1 - level / 100)
        return np.asarray(f.predicted_mean), np.asarray(ci)[:, 0], np.asarray(ci)[:, 1]

    fitted = np.asarray(res.fittedvalues, dtype=float)
    fitted[: season + 1] = np.nan
    return FittedModel("SARIMA", fitted, {"order": list(order), "seasonal_order": [*sorder, season], "aic": float(best[0])}, fc)


MODELS = {
    "Naive": (fit_naive, lambda freq: 2),
    "Drift": (fit_drift, lambda freq: 3),
    "Seasonal naive": (fit_seasonal_naive, lambda freq: 24 if freq == "M" else None),
    "Linear trend": (fit_linear, lambda freq: 4),
    "ARIMA": (fit_arima, lambda freq: 6 if freq == "A" else 24),
    "SARIMA": (fit_sarima, lambda freq: 36 if freq == "M" else None),
}


def build_series(df: pd.DataFrame, frequency: str) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    if frequency == "A":
        s = df.groupby("year")["trade_value"].sum().sort_index()
        s.index = s.index.astype(int)
        return s.astype(float)
    d = df.dropna(subset=["month"])
    g = d.groupby(["year", "month"])["trade_value"].sum()
    idx = pd.PeriodIndex([pd.Period(year=int(y), month=int(m), freq="M") for y, m in g.index])
    return pd.Series(g.values.astype(float), index=idx).sort_index()


def _expected_index(s: pd.Series, frequency: str):
    if frequency == "A":
        return pd.Index(range(int(s.index.min()), int(s.index.max()) + 1))
    return pd.period_range(s.index.min(), s.index.max(), freq="M")


def diagnose(s: pd.Series, frequency: str, cfg: ForecastConfig) -> tuple[pd.Series, list[str], list[str]]:
    warn, notes = [], []
    if s.empty:
        return s, ["No observations for the selected series."], notes
    full = _expected_index(s, frequency)
    missing = [p for p in full if p not in s.index]
    used = s
    if missing:
        warn.append(
            f"The series has {len(missing)} missing period(s): {', '.join(map(str, missing[:12]))}{'…' if len(missing) > 12 else ''}. "
            "Missing periods are not filled with zero; only the most recent uninterrupted stretch is used for modelling."
        )
        present = set(s.index)
        seg_end = s.index.max()
        seg = [seg_end]
        cur = seg_end
        while True:
            prev = cur - 1
            if prev in present:
                seg.append(prev)
                cur = prev
            else:
                break
        used = s.loc[sorted(seg)]
    n = len(used)
    short = 15 if frequency == "A" else 36
    if n < short:
        warn.append(
            f"Short series: {n} {'annual' if frequency == 'A' else 'monthly'} observations. Forecast uncertainty is high and "
            "model comparisons rest on few out-of-sample points; treat results as indicative only."
        )
    if n < cfg.min_train + 1:
        warn.append(f"Not enough observations for out-of-sample evaluation (need at least {cfg.min_train + 1}).")
    if (used == 0).any():
        notes.append(f"{int((used == 0).sum())} period(s) report a value of zero; MAPE excludes near-zero actuals.")
    pos = used[used > 0]
    if len(pos) >= 3:
        vol = float(np.std(np.diff(np.log(pos.values)), ddof=1))
        if vol > cfg.volatility_threshold:
            warn.append(f"Highly volatile series (standard deviation of log changes = {vol:.2f}). Large swings reduce forecast reliability.")
        notes.append(f"Volatility (std. of log changes): {vol:.2f}.")
    return used, warn, notes


def mase_scale(train: np.ndarray, m: int) -> float:
    if len(train) <= m:
        return np.nan
    d = np.abs(train[m:] - train[:-m])
    sc = float(np.mean(d))
    return sc if sc > 0 else np.nan


def compute_metrics(actual: np.ndarray, pred: np.ndarray, scales: np.ndarray | None, eps_share: float) -> dict:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    ok = ~np.isnan(pred) & ~np.isnan(actual)
    a, p = actual[ok], pred[ok]
    out = {"n_test": int(ok.sum()), "MAE": np.nan, "RMSE": np.nan, "MASE": np.nan, "MAPE": np.nan, "MAPE_excluded": 0}
    if a.size == 0:
        return out
    out["MAE"] = float(mean_absolute_error(a, p))
    out["RMSE"] = float(np.sqrt(mean_squared_error(a, p)))
    if scales is not None:
        sc = np.asarray(scales, dtype=float)[ok]
        valid = ~np.isnan(sc) & (sc > 0)
        if valid.any():
            out["MASE"] = float(np.mean(np.abs(a[valid] - p[valid]) / sc[valid]))
    eps = eps_share * float(np.mean(np.abs(a))) if a.size else 0
    keep = np.abs(a) > eps
    out["MAPE_excluded"] = int((~keep).sum())
    if keep.any():
        out["MAPE"] = float(np.mean(np.abs((a[keep] - p[keep]) / a[keep])) * 100)
    return out


def eligible_models(n: int, frequency: str) -> dict[str, int]:
    out = {}
    for name, (_, req) in MODELS.items():
        r = req(frequency)
        if r is not None and r <= n - 2:
            out[name] = r
    return out


def rolling_origin(y: np.ndarray, frequency: str, cfg: ForecastConfig, season: int) -> tuple[pd.DataFrame, pd.DataFrame, int, dict]:
    n = len(y)
    models = eligible_models(n, frequency)
    start = max([cfg.min_train] + list(models.values())) if models else n
    while models and n - start < 2:
        worst = max(models, key=models.get)
        models.pop(worst)
        start = max([cfg.min_train] + list(models.values())) if models else n
    rows = []
    failures = {}
    m = season if frequency == "M" and n > 2 * season else 1
    for origin in range(start, n):
        train = y[:origin]
        scale = mase_scale(train, m)
        row = {"origin_index": origin, "actual": y[origin], "scale": scale}
        for name in models:
            fit = MODELS[name][0]
            try:
                fm = fit(train, season)
                row[name] = float(fm.forecast(1, 80)[0][0])
            except Exception as exc:
                row[name] = np.nan
                failures.setdefault(name, str(exc)[:120])
        rows.append(row)
    bt = pd.DataFrame(rows)
    metrics = []
    for name in models:
        if bt.empty:
            continue
        met = compute_metrics(bt["actual"].values, bt[name].values, bt["scale"].values, cfg.mape_epsilon_share)
        met["model"] = name
        met["complexity"] = COMPLEXITY[name]
        metrics.append(met)
    mt = pd.DataFrame(metrics, columns=["model", "complexity", "n_test", "MAE", "RMSE", "MASE", "MAPE", "MAPE_excluded"])
    return bt, mt, start, failures


def select_model(mt: pd.DataFrame, tolerance_pct: float) -> tuple[str | None, str, str]:
    if mt.empty:
        return None, "", "No model could be evaluated out-of-sample."
    metric = "MASE" if mt["MASE"].notna().any() else "MAE"
    valid = mt.dropna(subset=[metric])
    if valid.empty:
        return None, metric, "No valid out-of-sample errors were produced."
    best_val = valid[metric].min()
    best_model = valid.loc[valid[metric].idxmin(), "model"]
    within = valid[valid[metric] <= best_val * (1 + tolerance_pct / 100)]
    chosen = within.sort_values(["complexity", metric]).iloc[0]["model"]
    reason = f"Lowest out-of-sample {metric}: {best_model} ({best_val:.3f}). "
    if chosen != best_model:
        reason += f"{chosen} is within {tolerance_pct:.0f}% of the best score and is simpler, so it is selected (parsimony rule)."
    else:
        reason += "No simpler model was within the parsimony tolerance, so it is selected."
    return chosen, metric, reason


def future_index(s: pd.Series, h: int, frequency: str):
    last = s.index.max()
    if frequency == "A":
        return [int(last) + i for i in range(1, h + 1)]
    return [last + i for i in range(1, h + 1)]


def series_hash(s: pd.Series, params: dict) -> str:
    payload = json.dumps({"index": [str(i) for i in s.index], "values": [round(float(v), 4) for v in s.values], "params": params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def run_forecast(s: pd.Series, frequency: str, cfg: ForecastConfig, season: int = 12) -> dict:
    used, warn, notes = diagnose(s, frequency, cfg)
    params = cfg.model_dump() | {"frequency": frequency, "season": season if frequency == "M" else None, "evaluation": "rolling-origin, one-step-ahead, expanding window"}
    result = {"series": s, "used": used, "warnings": warn, "notes": notes, "params": params, "disclaimer": DISCLAIMER, "data_hash": series_hash(used, params), "status": "ok"}
    if len(used) < 3:
        result["status"] = "insufficient"
        result["warnings"].append("At least 3 consecutive observations are required to produce any forecast.")
        return result
    y = used.values.astype(float)
    bt, mt, start, failures = rolling_origin(y, frequency, cfg, season)
    for name, msg in failures.items():
        notes.append(f"{name} failed on some training windows ({msg}); those origins are excluded from its error metrics.")
    chosen, metric, reason = select_model(mt, cfg.parsimony_tolerance_pct)
    if not bt.empty:
        bt.insert(0, "period", [str(used.index[i]) for i in bt["origin_index"]])
    result.update({"backtest": bt, "metrics": mt, "first_test_index": start, "selection_metric": metric, "selected": chosen, "selection_reason": reason})
    if chosen is None:
        chosen = "Naive"
        result["selected"] = chosen
        result["selection_reason"] = "Too few observations for out-of-sample comparison; the naive (last value) benchmark is shown as a reference only and has not been validated."
        result["status"] = "unvalidated"
    fidx = future_index(used, cfg.horizon, frequency)
    forecasts, fitted_all = [], {}
    candidates = list(mt["model"]) if not mt.empty else [chosen]
    for name in candidates:
        try:
            fm = MODELS[name][0](y, season)
            mean, lo, hi = fm.forecast(cfg.horizon, cfg.interval_level)
            fitted_all[name] = {"fitted": fm.fitted, "params": fm.params}
            for p, mu, a, b in zip(fidx, mean, lo, hi):
                forecasts.append(
                    {
                        "model": name,
                        "period": str(p),
                        "forecast": float(mu),
                        "lower": float(max(a, 0)) if not np.isnan(a) else np.nan,
                        "upper": float(b),
                        "lower_truncated": bool(not np.isnan(a) and a < 0),
                    }
                )
        except Exception as exc:
            notes.append(f"{name} could not be fitted on the full series: {str(exc)[:120]}")
    fc = pd.DataFrame(forecasts)
    if fc.empty or chosen not in set(fc["model"]):
        result["status"] = "failed"
        result["warnings"].append("The selected model could not produce a forecast.")
        return result
    if fc["lower_truncated"].any():
        notes.append("Some lower prediction-interval bounds fell below zero and were truncated at zero, since trade values cannot be negative.")
    result["forecasts"] = fc
    result["fitted"] = pd.DataFrame({"period": [str(i) for i in used.index], "actual": y, "fitted": fitted_all[chosen]["fitted"] if chosen in fitted_all else np.nan})
    result["model_params"] = {k: v["params"] for k, v in fitted_all.items()}
    result["future_index"] = [str(p) for p in fidx]
    return result


def period_to_timestamp(values, frequency: str) -> list:
    if frequency == "A":
        return [pd.Timestamp(year=int(v), month=1, day=1) for v in values]
    return [pd.Period(v, freq="M").to_timestamp() for v in values]
