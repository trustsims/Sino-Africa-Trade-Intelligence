import numpy as np
import pandas as pd
import pytest

from src import forecasting as f
from src.schema import ForecastConfig

SERIES = pd.Series([100.0, 120.0, 115.0, 140.0, 150.0, 145.0, 170.0, 180.0, 175.0, 200.0], index=range(2015, 2025))


def test_naive_and_drift_forecasts():
    y = np.array([10.0, 12.0, 14.0, 16.0])
    mean, lo, hi = f.fit_naive(y).forecast(3, 95)
    assert list(mean) == [16.0, 16.0, 16.0]
    assert (hi - mean)[1] == pytest.approx((hi - mean)[0] * np.sqrt(2))
    mean, _, _ = f.fit_drift(y).forecast(2, 95)
    assert list(mean) == pytest.approx([18.0, 20.0])


def test_seasonal_naive():
    y = np.tile(np.arange(12, dtype=float), 3)
    mean, _, _ = f.fit_seasonal_naive(y, 12).forecast(14, 80)
    assert list(mean[:12]) == list(np.arange(12, dtype=float))
    assert mean[12] == 0.0


def test_linear_trend_recovers_slope():
    y = 5.0 + 2.0 * np.arange(10)
    fm = f.fit_linear(y)
    assert fm.params["slope_per_period"] == pytest.approx(2.0)
    mean, _, _ = fm.forecast(1, 95)
    assert mean[0] == pytest.approx(25.0)


def test_metrics():
    actual = np.array([100.0, 0.0, 50.0])
    pred = np.array([110.0, 5.0, 40.0])
    m = f.compute_metrics(actual, pred, np.array([10.0, 10.0, 10.0]), 0.01)
    assert m["MAE"] == pytest.approx(25 / 3)
    assert m["RMSE"] == pytest.approx(np.sqrt((100 + 25 + 100) / 3))
    assert m["MASE"] == pytest.approx(25 / 3 / 10)
    assert m["MAPE_excluded"] == 1
    assert m["MAPE"] == pytest.approx((0.1 + 0.2) / 2 * 100)
    assert f.mase_scale(np.array([1.0, 3.0, 6.0]), 1) == pytest.approx(2.5)
    assert np.isnan(f.mase_scale(np.array([5.0, 5.0, 5.0]), 1))


def test_time_ordered_rolling_origin():
    cfg = ForecastConfig(min_train=5)
    bt, mt, start, _ = f.rolling_origin(SERIES.values, "A", cfg, 12)
    assert start >= 5
    assert list(bt["origin_index"]) == list(range(start, len(SERIES)))
    assert bt["origin_index"].is_monotonic_increasing
    naive = bt["Naive"].values
    assert list(naive) == list(SERIES.values[start - 1 : -1])
    assert set(mt["n_test"]) == {len(SERIES) - start}


def test_short_series_warning_and_selection():
    res = f.run_forecast(SERIES, "A", ForecastConfig(horizon=3))
    assert any("Short series" in w for w in res["warnings"])
    assert res["selected"] in set(res["metrics"]["model"])
    assert len(res["forecasts"][res["forecasts"]["model"] == res["selected"]]) == 3
    assert (res["forecasts"]["lower"].dropna() >= 0).all()
    assert "ARIMA" in set(res["metrics"]["model"])


def test_missing_periods_use_latest_contiguous_segment():
    s = SERIES.drop([2018])
    res = f.run_forecast(s, "A", ForecastConfig(horizon=2, min_train=3))
    assert any("missing period" in w for w in res["warnings"])
    assert list(res["used"].index) == list(range(2019, 2025))
    assert res["forecasts"]["period"].iloc[0] == "2025"


def test_insufficient_data():
    res = f.run_forecast(pd.Series([1.0, 2.0], index=[2023, 2024]), "A", ForecastConfig())
    assert res["status"] == "insufficient"
    res2 = f.run_forecast(pd.Series([1.0, 2.0, 3.0, 4.0], index=range(2021, 2025)), "A", ForecastConfig(min_train=5))
    assert res2["status"] == "unvalidated" and res2["selected"] == "Naive"


def test_reproducible_runs():
    cfg = ForecastConfig(horizon=3)
    a = f.run_forecast(SERIES, "A", cfg)
    b = f.run_forecast(SERIES, "A", cfg)
    assert a["data_hash"] == b["data_hash"]
    pd.testing.assert_frame_equal(a["forecasts"], b["forecasts"])
    pd.testing.assert_frame_equal(a["metrics"], b["metrics"])
    c = f.run_forecast(SERIES, "A", ForecastConfig(horizon=4))
    assert c["data_hash"] != a["data_hash"]


def test_parsimony_selection():
    mt = pd.DataFrame(
        [
            {"model": "Naive", "complexity": 1, "MASE": 1.02, "MAE": 1},
            {"model": "ARIMA", "complexity": 4, "MASE": 1.0, "MAE": 1},
            {"model": "Drift", "complexity": 2, "MASE": 1.2, "MAE": 1},
        ]
    )
    chosen, metric, _ = f.select_model(mt, 5.0)
    assert metric == "MASE" and chosen == "Naive"
    chosen, _, _ = f.select_model(mt, 0.0)
    assert chosen == "ARIMA"


def test_monthly_series_with_sarima():
    idx = pd.period_range("2019-01", periods=48, freq="M")
    rng = np.random.default_rng(0)
    vals = 100 + 10 * np.sin(np.arange(48) * 2 * np.pi / 12) + np.arange(48) + rng.normal(0, 1, 48)
    res = f.run_forecast(pd.Series(vals, index=idx), "M", ForecastConfig(horizon=6, min_train=24))
    models = set(res["metrics"]["model"])
    assert {"Seasonal naive", "SARIMA"} <= models
    assert res["forecasts"]["period"].iloc[0] == "2023-01"


def test_build_series_never_fills_missing_with_zero():
    df = pd.DataFrame({"year": [2015, 2017], "month": [pd.NA, pd.NA], "trade_value": [1.0, 2.0]})
    s = f.build_series(df, "A")
    assert list(s.index) == [2015, 2017]
