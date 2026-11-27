import numpy as np
import pandas as pd
import pytest

from src import data_ingestion as di
from src import mirror_analysis as mi
from tests.conftest import csv_bytes, synthetic_rows


def clean(rows) -> pd.DataFrame:
    raw, _ = di.read_table("t.csv", csv_bytes(pd.DataFrame(rows)))
    return di.preview_pipeline(raw, di.suggest_mapping(raw.columns), "TEST")["clean"]


def test_discrepancy_formulas(mirror_df):
    d = clean(mirror_df.to_dict("records"))
    res = mi.mirror_compare(d, "894", "156", 6)
    assert res["status"] == "ok"
    r = res["records"]
    assert (r["match_status"] == "matched").all()
    row = r[(r["year"] == 2018) & (r["hs_code"] == "260300")].iloc[0]
    assert row["value_a"] == pytest.approx(100.0)
    assert row["value_b"] == pytest.approx(110.0)
    assert row["abs_discrepancy"] == pytest.approx(10.0)
    assert row["pct_discrepancy"] == pytest.approx(10.0)
    assert row["mirror_ratio"] == pytest.approx(1.1)
    assert res["summary"]["match_rate_pct"] == pytest.approx(100.0)
    assert res["summary"]["aggregate_pct_discrepancy"] == pytest.approx(10.0)
    an = res["annual"]
    assert an.loc[an["year"] == 2018, "abs_discrepancy"].iloc[0] == pytest.approx(41.0)


def test_zero_denominator_is_undefined():
    a = synthetic_rows(894, 156, "X", years=[2020], codes=[("260300", "ore", 0.0)])
    b = synthetic_rows(156, 894, "M", years=[2020], codes=[("260300", "ore", 50.0)])
    res = mi.mirror_compare(clean(a + b), "894", "156", 6)
    r = res["records"].iloc[0]
    assert r["abs_discrepancy"] == pytest.approx(50.0)
    assert np.isnan(r["pct_discrepancy"]) and np.isnan(r["mirror_ratio"])
    assert res["summary"]["undefined_pct"] == 1


def test_unmatched_records_and_product_matching():
    a = synthetic_rows(894, 156, "X", years=[2020], codes=[("260300", "ore", 100.0), ("120740", "seeds", 5.0)])
    b = synthetic_rows(156, 894, "M", years=[2020], codes=[("260300", "ore", 104.0), ("440799", "wood", 7.0)])
    res = mi.mirror_compare(clean(a + b), "894", "156", 6)
    r = res["records"].set_index("hs_code")
    assert r.loc["260300", "match_status"] == "matched"
    assert r.loc["120740", "match_status"] == "Zambia only" and np.isnan(r.loc["120740", "abs_discrepancy"])
    assert r.loc["440799", "match_status"] == "China only" and np.isnan(r.loc["440799", "value_a"])
    sm = res["summary"]
    assert sm["records_matched"] == 1 and sm["a_only"] == 1 and sm["b_only"] == 1
    assert sm["match_rate_pct"] == pytest.approx(100 / 3)
    assert sm["value_coverage_pct"] == pytest.approx(100 / 105 * 100)


def test_classification_mismatch_is_incomparable():
    a = synthetic_rows(894, 156, "X", years=[2020], codes=[("260300", "ore", 100.0)])
    b = synthetic_rows(156, 894, "M", years=[2020], codes=[("260300", "ore", 104.0)])
    for r in b:
        r["classificationCode"] = "H6"
    res = mi.mirror_compare(clean(a + b), "894", "156", 6)
    assert set(res["records"]["match_status"]) == {"incomparable (classification version differs)"}
    assert res["summary"]["records_matched"] == 0


def test_single_reporter_is_insufficient(synthetic_df):
    res = mi.mirror_compare(clean(synthetic_df.to_dict("records")), "894", "156", 6)
    assert res["status"] == "insufficient"
    assert "China as reporter" in res["message"] and "never estimated" in res["message"]
