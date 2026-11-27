import numpy as np
import pandas as pd
import pytest

from src import data_ingestion as di
from src import trade_analytics as ta
from tests.conftest import csv_bytes, synthetic_rows


def clean(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    raw, _ = di.read_table("t.csv", csv_bytes(df))
    out = di.preview_pipeline(raw, di.suggest_mapping(raw.columns), "TEST")["clean"].copy()
    out["dataset_id"] = 1
    return out


def test_annual_totals(synthetic_df):
    d = clean(synthetic_rows())
    a = ta.annual_totals(d)
    assert list(a["year"]) == [2018, 2019, 2020, 2021, 2022]
    assert a.loc[a["year"] == 2018, "trade_value"].iloc[0] == pytest.approx(410.0)
    assert a.loc[a["year"] == 2019, "trade_value"].iloc[0] == pytest.approx(440.0)
    assert a.loc[a["year"] == 2019, "yoy_pct"].iloc[0] == pytest.approx(30 / 410 * 100)
    assert np.isnan(a.loc[a["year"] == 2018, "yoy_pct"].iloc[0])


def test_yoy_zero_denominator_and_gaps():
    s = pd.Series([0.0, 50.0, 60.0, 90.0], index=[2015, 2016, 2017, 2019])
    g = ta.yoy_growth(s)
    assert np.isnan(g[2015]) and np.isnan(g[2016])
    assert g[2017] == pytest.approx(20.0)
    assert np.isnan(g[2019])
    assert np.isnan(ta.safe_pct_change(10, 0))


def test_cagr():
    assert ta.cagr(100, 121, 2) == pytest.approx(10.0)
    assert np.isnan(ta.cagr(0, 100, 3)) and np.isnan(ta.cagr(100, 0, 3)) and np.isnan(ta.cagr(100, 120, 0))


def test_product_ranking():
    d = clean(synthetic_rows())
    r = ta.product_ranking(d)
    assert list(r["hs_code"]) == ["740311", "260300", "120740"]
    assert r["share_pct"].sum() == pytest.approx(100.0)
    assert r["cumulative_share_pct"].iloc[-1] == pytest.approx(100.0)
    assert list(r["rank"]) == [1, 2, 3]
    assert len(ta.product_ranking(d, 2)) == 2


def test_hhi_and_concentration_ratios():
    assert ta.hhi([50, 50]) == pytest.approx(0.5)
    assert ta.hhi([100]) == pytest.approx(1.0)
    assert ta.hhi([25, 25, 25, 25]) == pytest.approx(0.25)
    assert np.isnan(ta.hhi([]))
    assert ta.hhi([60, 30, 10]) == pytest.approx(0.36 + 0.09 + 0.01)
    assert ta.normalized_hhi(0.25, 4) == pytest.approx(0.0)
    assert ta.normalized_hhi(1.0, 4) == pytest.approx(1.0)
    assert ta.concentration_ratio([60, 30, 10], 1) == pytest.approx(60.0)
    assert ta.concentration_ratio([60, 30, 10], 3) == pytest.approx(100.0)
    assert ta.hhi_band(1000).startswith("unconcentrated") and ta.hhi_band(3000).startswith("highly")


def test_concentration_by_year():
    d = clean(synthetic_rows())
    c = ta.concentration_by_year(d)
    first = c.iloc[0]
    shares = np.array([100, 300, 10]) / 410
    assert first["hhi"] == pytest.approx((shares**2).sum())
    assert first["effective_products"] == pytest.approx(1 / (shares**2).sum())
    assert first["products_observed"] == 3


def test_copper_breakdown():
    d = clean(synthetic_rows())
    cb = ta.copper_breakdown(d)
    t = cb["table"]
    assert cb["ore_available"]
    assert t.loc[t["year"] == 2018, "copper_ore_2603"].iloc[0] == pytest.approx(100)
    assert t.loc[t["year"] == 2018, "copper_related"].iloc[0] == pytest.approx(400)
    assert t.loc[t["year"] == 2018, "ore_share_pct"].iloc[0] == pytest.approx(100 / 410 * 100)
    totals = d.iloc[0:0]
    assert not ta.copper_breakdown(totals)["available"]


def test_reconciliation_and_levels():
    rows = synthetic_rows()
    rows.append(
        {
            "refYear": 2018,
            "reporterCode": 894,
            "partnerCode": 156,
            "flowCode": "X",
            "classificationCode": "H5",
            "cmdCode": "TOTAL",
            "cmdDesc": "All",
            "primaryValue": 500,
            "netWgt": None,
            "qtyUnitAbbr": "",
        }
    )
    d = clean(rows)
    assert ta.available_levels(d) == [0, 6]
    assert ta.default_level([0, 6]) == 6
    rec = ta.reconciliation(d, 6)
    assert rec.iloc[0]["coverage_pct"] == pytest.approx(410 / 500 * 100)
    assert ta.at_level(d, 6)["hs_level"].eq(6).all()


def test_dedupe_across_datasets():
    d1 = clean(synthetic_rows())
    d2 = d1.copy()
    d2["dataset_id"] = 2
    both = pd.concat([d1, d2], ignore_index=True)
    out, dropped = ta.dedupe_across_datasets(both)
    assert dropped == len(d1) and set(out["dataset_id"]) == {2}


def test_trade_balance_and_observations():
    d = clean(synthetic_rows() + synthetic_rows(flow="M", codes=[("870323", "TEST cars", 50.0)]))
    tb = ta.trade_balance(d, "894", "156")
    assert tb.iloc[0]["balance"] == pytest.approx(410 - 50)
    notes = ta.observations(d[d["flow"] == "X"], "USD", 1.0)
    assert any("Largest annual increase" in n for n in notes)
    assert any("Leading product" in n and "740311" in n for n in notes)


def test_period_and_month_filters_select_exact_months():
    from src import ui

    rows = [{"year": y, "month": m, "trade_value": 1.0} for y in (2021, 2022, 2023) for m in range(1, 13)]
    df = pd.DataFrame(rows)
    both = ui.apply_filters(df, {"period": (202106, 202303), "months": [1, 2, 3]})
    assert sorted(zip(both["year"], both["month"])) == [(2022, 1), (2022, 2), (2022, 3), (2023, 1), (2023, 2), (2023, 3)]
    span = ui.apply_filters(df, {"period": (202106, 202303)})
    assert len(span) == 22
    assert ui.apply_filters(df, {"period": (202106, 202303)}, skip=("period",)).shape[0] == 36
    assert ui.period_label({"period": (202106, 202303), "months": [3, 1]}) == "Jun 2021–Mar 2023 (Jan, Mar only)"
    assert ui.period_label({"years": (2015, 2024)}) == "2015–2024"
