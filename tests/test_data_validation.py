import io

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from src import data_ingestion as di
from src.data_cleaning import normalize_hs
from src.schema import ColumnMapping, normalize_country_code, normalize_flow
from tests.conftest import csv_bytes


def run(df: pd.DataFrame, mapping: dict | None = None):
    raw, _ = di.read_table("test.csv", csv_bytes(df))
    return di.preview_pipeline(raw, mapping or di.suggest_mapping(raw.columns), "TEST")


def rules(result) -> set:
    return set(result["issues"]["rule"])


def test_valid_csv_import(synthetic_df):
    res = run(synthetic_df)
    sm = res["summary"]
    assert sm["raw_rows"] == 15 and sm["clean_rows"] == 15 and sm["excluded_rows"] == 0
    assert sm["perspective"] == "Zambia → China (X)"
    assert set(res["clean"]["flow"]) == {"X"}
    assert res["clean"]["hs_code"].str.len().eq(6).all()
    assert (res["clean"]["valuation_basis"] == "FOB").all() and res["clean"]["valuation_assumed"].all()


def test_valid_excel_import(synthetic_df):
    buf = io.BytesIO()
    synthetic_df.to_excel(buf, index=False, engine="openpyxl")
    raw, info = di.read_table("test.xlsx", buf.getvalue())
    assert info["rows"] == 15
    res = di.preview_pipeline(raw, di.suggest_mapping(raw.columns), "TEST")
    assert res["summary"]["clean_rows"] == 15
    assert res["clean"]["trade_value"].sum() == pytest.approx(synthetic_df["primaryValue"].sum())


def test_semicolon_and_cp1252_csv():
    text = "refYear;reporterCode;partnerCode;flowCode;cmdCode;cmdDesc;primaryValue\n2020;894;156;X;260300;Minérais;1000\n"
    raw, info = di.read_table("t.csv", text.encode("cp1252"))
    assert info["delimiter"] == ";" and raw.loc[0, "cmdDesc"] == "Minérais"


def test_missing_required_columns():
    with pytest.raises(ValidationError):
        ColumnMapping(columns={"hs_code": "cmdCode"}, constants={})
    with pytest.raises(ValidationError):
        ColumnMapping(columns={"year": "refYear", "trade_value": "primaryValue"}, constants={})
    ok = ColumnMapping(columns={"year": "y", "trade_value": "v"}, constants={"reporter_code": "894", "partner_code": "156", "flow": "X"})
    assert ok.constants["flow"] == "X"


def test_invalid_years_and_malformed_values(synthetic_df):
    df = synthetic_df.astype(object)
    df.loc[0, "refYear"] = 1800
    df.loc[1, "refYear"] = "abc"
    df.loc[2, "primaryValue"] = "12x"
    df.loc[3, "primaryValue"] = ""
    df.loc[4, "primaryValue"] = -5
    res = run(df)
    assert {"V01", "V02", "V03", "V04", "V05"} <= rules(res)
    assert res["summary"]["excluded_rows"] == 5
    assert res["summary"]["clean_rows"] == 10
    assert not (res["clean"]["trade_value"] == 0).any()


def test_exact_and_conflicting_duplicates(synthetic_df):
    df = pd.concat([synthetic_df, synthetic_df.iloc[[0]]], ignore_index=True)
    res = run(df)
    assert "V11" in rules(res) and res["summary"]["clean_rows"] == 15
    conflict = synthetic_df.iloc[[1]].copy()
    conflict["primaryValue"] = 999999
    res2 = run(pd.concat([synthetic_df, conflict], ignore_index=True))
    assert "V12" in rules(res2)
    assert res2["summary"]["clean_rows"] == 14


def test_missing_optional_values_kept_as_missing(synthetic_df):
    df = synthetic_df.astype(object)
    df.loc[0, "netWgt"] = ""
    df.loc[1, "netWgt"] = "n/a"
    res = run(df)
    clean = res["clean"]
    assert clean["net_weight_kg"].isna().sum() == 2
    assert "V14" in rules(res)
    assert res["summary"]["clean_rows"] == 15


def test_currency_and_unit_consistency_checks(synthetic_df):
    df = synthetic_df.copy()
    df["currency"] = "USD"
    df.loc[0, "currency"] = "EUR"
    df.loc[3, "qtyUnitAbbr"] = "t"
    res = run(df)
    checks = {c["check"] for c in res["checks"]}
    assert {"D01", "D02"} <= checks
    assert set(res["clean"]["currency"]) == {"USD", "EUR"}


def test_classification_conflict_and_hs_padding(synthetic_df):
    df = synthetic_df.copy()
    df.loc[0, "classificationCode"] = "H6"
    df["cmdCode"] = df["cmdCode"].astype(str)
    df.loc[2, "cmdCode"] = "20740"
    res = run(df)
    assert "D03" in {c["check"] for c in res["checks"]}
    assert "V07" in rules(res)
    assert "020740" in set(res["clean"]["hs_code"])


def test_breakdown_rows_excluded_only_when_aggregate_exists(synthetic_df):
    df = synthetic_df.copy()
    df["motCode"] = 0
    extra = df.iloc[[0]].copy()
    extra["motCode"] = 1000
    res = run(pd.concat([df, extra], ignore_index=True))
    assert "V13" in rules(res)
    assert res["summary"]["clean_rows"] == 15


def test_normalizers():
    assert normalize_flow("Export") == "X" and normalize_flow("M") == "M" and normalize_flow("2") == "X" and normalize_flow("?") is None
    assert normalize_country_code("ZMB") == "894" and normalize_country_code("China") == "156" and normalize_country_code("894.0") == "894"
    assert normalize_hs("10121") == ("010121", True) and normalize_hs("TOTAL") == ("TOTAL", False) and normalize_hs("26.03")[0] is None
    assert normalize_hs(np.nan) == (None, False)


def test_invalid_upload_handling():
    with pytest.raises(di.IngestionError):
        di.read_table("data.exe", b"abc")
    with pytest.raises(di.IngestionError):
        di.read_table("empty.csv", b"")
    with pytest.raises(di.IngestionError):
        di.read_table("header_only.csv", b"a,b,c\n")
    with pytest.raises(di.IngestionError):
        di.read_table("bad.xlsx", b"not a workbook")
    with pytest.raises(di.IngestionError):
        di.read_table("bad.csv", b"a,b\n1,2,3,4\n5,6\n")


def test_file_size_limit(monkeypatch):
    from src import config

    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0)
    with pytest.raises(di.IngestionError, match="limit"):
        di.read_table("x.csv", b"a,b\n1,2\n")


def test_constants_mapping_for_non_comtrade_file():
    df = pd.DataFrame({"Year": [2020, 2021], "HS": ["260300", "260300"], "Value USD": ["1,000", "2,000"]})
    raw, _ = di.read_table("x.csv", csv_bytes(df))
    mapping = {
        "columns": {"year": "Year", "hs_code": "HS", "trade_value": "Value USD"},
        "constants": {"reporter_code": "Zambia", "partner_code": "CHN", "flow": "Export", "currency": "USD"},
    }
    res = di.preview_pipeline(raw, mapping, "TEST")
    clean = res["clean"]
    assert list(clean["trade_value"]) == [1000.0, 2000.0]
    assert set(clean["reporter_code"]) == {"894"} and set(clean["partner_code"]) == {"156"} and set(clean["flow"]) == {"X"}


def test_trailing_delimiter_rows_are_accepted():
    text = "refYear,reporterCode,partnerCode,flowCode,cmdCode,primaryValue\n2020,894,156,X,260300,1000,\n2021,894,156,X,260300,1200,\n"
    raw, info = di.read_table("comtrade.csv", text.encode())
    assert list(raw["primaryValue"]) == ["1000", "1200"]
    assert info["trailing_delimiters_removed"] == 2
    text2 = "refYear,reporterCode,partnerCode,flowCode,cmdCode,primaryValue,\n2020,894,156,X,260300,1000\n"
    raw2, _ = di.read_table("comtrade.csv", text2.encode())
    assert list(raw2.columns)[-1] == "primaryValue"


def test_quoted_commas_are_preserved():
    text = 'refYear,cmdDesc,primaryValue\n2020,"Copper; ores, concentrates",1000\n'
    raw, _ = di.read_table("q.csv", text.encode())
    assert raw.loc[0, "cmdDesc"] == "Copper; ores, concentrates"
