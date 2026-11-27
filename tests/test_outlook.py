import math

import pandas as pd
import pytest

from src import outlook as ol


def test_production_path_linear_then_flat():
    p = ol.production_path(2025, 1000.0, 3000.0, 2029, 2032)
    assert list(p.index) == list(range(2025, 2033))
    assert p[2025] == 1000.0
    assert p[2027] == pytest.approx(2000.0)
    assert p[2029] == 3000.0 and p[2032] == 3000.0


def test_production_path_target_in_start_year_is_flat():
    p = ol.production_path(2025, 900.0, 900.0, 2025, 2030)
    assert (p == 900.0).all()


def test_required_growth():
    assert ol.required_growth(100.0, 2025, 121.0, 2027) == pytest.approx(10.0)
    assert math.isnan(ol.required_growth(100.0, 2025, 200.0, 2025))


def test_scenario_frame_values_and_band():
    inputs = ol.BaseInputs(2024, 2_000.0, 250.0, 100.0, 8.0, 0.25)
    f = ol.scenario_frame([{"scenario": "A", "target_t": 2000.0, "target_year": 2027}], inputs, 2025, 1000.0, 2030, 20)
    row = f[f["year"] == 2030].iloc[0]
    assert row["to_china_t"] == pytest.approx(500.0)
    assert row["value"] == pytest.approx(4000.0)
    assert row["low"] == pytest.approx(3200.0) and row["high"] == pytest.approx(4800.0)


def _obs(rows):
    return pd.DataFrame(rows, columns=["reporter_code", "partner_code", "flow", "hs_level", "hs_code", "year", "trade_value", "net_weight_kg"])


def test_base_inputs_uses_weighted_rows_for_unit_value():
    df = _obs([
        ("894", "156", "X", 6, "740311", 2024, 800.0, 100_000.0),
        ("894", "156", "X", 6, "260300", 2024, 200.0, None),
        ("894", "156", "X", 6, "120740", 2024, 50.0, 1_000.0),
    ])
    b = ol.base_inputs(df, 2024, 1000.0)
    assert b.value == pytest.approx(1000.0)
    assert b.unit_value == pytest.approx(8.0)
    assert b.tonnes == pytest.approx(125.0)
    assert b.value_coverage_pct == pytest.approx(80.0)
    assert b.share == pytest.approx(0.125)


def test_base_inputs_missing_year_returns_none():
    df = _obs([("894", "156", "X", 6, "740311", 2023, 800.0, 100_000.0)])
    assert ol.base_inputs(df, 2024, 1000.0) is None


def test_milestones():
    assert ol.milestones(2024, 10) == [2029, 2034]
    assert ol.milestones(2024, 7) == [2029]


def test_nearest_scenario_orders_by_gap():
    frame = pd.DataFrame({"scenario": ["A", "A", "B", "B"], "year": [2025, 2026, 2025, 2026], "value": [10.0, 12.0, 20.0, 30.0]})
    obs = pd.Series([11.0, 12.0], index=[2025, 2026])
    near = ol.nearest_scenario(frame, obs)
    assert near.iloc[0]["scenario"] == "A"
    assert ol.nearest_scenario(frame, pd.Series([1.0], index=[2020])).empty


def test_projection_and_balance_end_to_end():
    years = list(range(2014, 2025))
    ex = pd.Series([100.0 + 5 * i for i in range(11)], index=years)
    im = pd.Series([50.0 + 8 * i for i in range(11)], index=years)
    res = ol.project({"exports": ex, "imports": im}, 10, 95)
    t = ol.projection_table(res, [2029, 2034])
    assert set(t["key"]) == {"exports", "imports"}
    assert {"2029", "2034 upper"} <= set(t.columns)
    b = ol.balance_paths(res)
    assert set(b["basis"]) == {"Selected models", "Linear trends"}
    assert b["year"].min() == 2025 and b["year"].max() == 2034
