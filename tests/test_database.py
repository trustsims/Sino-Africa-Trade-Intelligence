import io
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import inspect

from src import data_ingestion as di
from src import database, reporting
from tests.conftest import csv_bytes, synthetic_rows

ROOT = Path(__file__).resolve().parent.parent


def write_csv(tmp_path, rows, name="data.csv") -> Path:
    p = tmp_path / name
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def test_database_initialization(engine):
    tables = set(inspect(engine).get_table_names())
    assert {
        "datasets",
        "trade_observations",
        "raw_records",
        "products",
        "classification_mappings",
        "import_logs",
        "forecast_runs",
        "app_settings",
        "data_sources",
        "schema_version",
    } <= tables
    assert database.schema_version(engine) == 1
    database.init_db(engine)
    assert database.schema_version(engine) == 1


def test_import_persists_across_restart(engine, tmp_path):
    p = write_csv(tmp_path, synthetic_rows())
    original = p.read_bytes()
    out = di.import_file(engine, p)
    assert out["status"] == "imported"
    assert p.read_bytes() == original
    db_file = database.database_file(engine)
    database.dispose_engines()
    reopened = database.init_db(database.get_engine(db_file))
    df = database.load_observations(reopened)
    assert len(df) == 15
    assert len(database.load_raw_records(reopened, out["dataset_id"])) == 15
    assert database.list_datasets(reopened).iloc[0]["status"] == "complete"


def test_repeat_import_is_blocked(engine, tmp_path):
    p = write_csv(tmp_path, synthetic_rows())
    assert di.import_file(engine, p)["status"] == "imported"
    again = di.import_file(engine, p)
    assert again["status"] == "duplicate"
    assert len(database.load_observations(engine)) == 15


def test_overlapping_datasets_counted_once(engine, tmp_path):
    from src.trade_analytics import dedupe_across_datasets

    di.import_file(engine, write_csv(tmp_path, synthetic_rows(), "a.csv"))
    rows = synthetic_rows()
    rows[0]["netWgt"] = 1
    out = di.import_file(engine, write_csv(tmp_path, rows, "b.csv"))
    assert out["status"] == "imported" and len(out["overlap"]) == 1
    df, dropped = dedupe_across_datasets(database.load_observations(engine))
    assert dropped == 15 and len(df) == 15


def test_invalid_upload_and_empty_result(engine, tmp_path):
    with pytest.raises(di.IngestionError):
        di.import_file(engine, tmp_path / "missing.csv")
    bad = write_csv(tmp_path, [{"refYear": "x", "reporterCode": 894, "partnerCode": 156, "flowCode": "X", "cmdCode": "260300", "primaryValue": "?"}])
    out = di.import_file(engine, bad)
    assert out["status"] == "empty"
    assert database.list_datasets(engine).empty


def test_interrupted_import_recovery(engine):
    with database.session_scope(engine) as s:
        s.add(database.Dataset(name="half", file_hash="abc", status="importing"))
    database.init_db(engine)
    ds = database.list_datasets(engine)
    assert ds.iloc[0]["status"] == "failed" and not ds.iloc[0]["is_active"]


def test_activate_reprocess_delete(engine, tmp_path):
    out = di.import_file(engine, write_csv(tmp_path, synthetic_rows()))
    ds_id = out["dataset_id"]
    database.set_dataset_active(engine, ds_id, False)
    assert database.load_observations(engine).empty
    database.set_dataset_active(engine, ds_id, True)
    res = di.reprocess_dataset(engine, ds_id)
    assert res["summary"]["clean_rows"] == 15 and len(database.load_observations(engine)) == 15
    path = di.write_processed(engine, ds_id)
    assert path.exists()
    database.delete_dataset(engine, ds_id)
    assert database.load_observations(engine, active_only=False).empty
    assert "delete" in set(database.import_logs(engine)["action"])


def test_mappings_settings_forecast_runs_backup(engine, tmp_path):
    with pytest.raises(ValueError):
        database.add_mapping(engine, "H5", "260300", "H6", "260300", "")
    with pytest.raises(ValueError):
        database.add_mapping(engine, "H5", "2603", "H6", "260300", "WCO table")
    database.add_mapping(engine, "H5", "260300", "H6", "260300", "WCO correlation table")
    assert len(database.list_mappings(engine)) == 1
    database.set_setting(engine, "top_n", 20)
    assert database.get_settings(engine)["top_n"] == 20
    run_id = database.save_forecast_run(
        engine,
        {
            "series_label": "test",
            "frequency": "A",
            "horizon": 3,
            "selected_model": "Naive",
            "data_hash": "h",
            "parameters": {},
            "metrics": [],
            "forecast": [],
            "warnings": [],
            "dataset_ids": [1],
        },
    )
    assert database.list_forecast_runs(engine).iloc[0]["id"] == run_id
    dest = database.backup_database(engine, tmp_path / "backup.db")
    assert dest.exists() and dest.stat().st_size > 0


def test_classification_mapping_application():
    from src.data_cleaning import apply_classification_mappings

    df = pd.DataFrame(
        {
            "classification": ["H5", "H6", "H5"],
            "hs_code": ["260300", "260300", "120740"],
            "hs_level": [6, 6, 6],
            "chapter": ["26", "26", "12"],
            "section": ["V", "V", "II"],
            "trade_value": [1.0, 2.0, 3.0],
        }
    )
    maps = pd.DataFrame([{"from_classification": "H5", "from_code": "260300", "to_classification": "H6", "to_code": "260300"}])
    out, info = apply_classification_mappings(df, maps, "H6")
    assert info["mapped_rows"] == 1 and info["unmapped_codes"] == ["H5:120740"]
    assert list(out["classification"]) == ["H6", "H6", "H5"]


def test_report_exports(engine, tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    assert reporting.to_csv_bytes(df).startswith(b"\xef\xbb\xbfa,b")
    xl = reporting.to_excel_bytes({"Data": df, "Very long sheet name that exceeds limits": df}, {"Generated": "now"})
    book = pd.read_excel(io.BytesIO(xl), sheet_name=None)
    assert set(book) == {"About", "Data", "Very long sheet name that excee"}
    annual = pd.DataFrame({"series": ["Zambia → China (Export)"] * 2, "year": [2020, 2021], "trade_value": [1e9, 1.2e9], "yoy_pct": [None, 20.0]})
    pdf = reporting.build_pdf_report(
        {
            "title": "Test − report",
            "filters": {"Period": "2020–2021"},
            "synthetic": True,
            "kpis": [("Total", "$2.2B")],
            "observations": ["Exports rose → by 20%."],
            "annual": annual,
            "scale": 1e6,
            "scale_label": "Million USD",
            "warnings": ["D08 gap"],
        }
    )
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_csv_bytes_helper_roundtrip():
    df = pd.DataFrame(synthetic_rows())
    raw, _ = di.read_table("x.csv", csv_bytes(df))
    assert len(raw) == len(df)


def test_app_startup_and_pages(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    db = tmp_path / "app.db"
    monkeypatch.setenv("TRADE_DB_PATH", str(db))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert any("No trade data" in m.value for m in at.markdown)
    eng = database.init_db(database.get_engine(db))
    di.import_file(eng, write_csv(tmp_path, synthetic_rows() + synthetic_rows(156, 894, "M", scale=1.1)))
    pages = [
        "views/home.py",
        "views/trade_explorer.py",
        "views/product_composition.py",
        "views/trade_mirror.py",
        "views/copper_forecasting.py",
        "views/trade_outlook.py",
        "views/data_management.py",
        "views/reports.py",
        "views/methodology.py",
        "views/settings.py",
    ]
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.run()
    for p in pages:
        at.switch_page(p)
        at.run()
        assert not at.exception, f"{p}: {[e.value for e in at.exception]}"
    at.switch_page("views/home.py")
    at.run()
    labels = [m.label for m in at.metric]
    assert any("Exports" in lbl for lbl in labels)


def test_theme_toggle_persists_and_restyles_charts(tmp_path, monkeypatch):
    import plotly.graph_objects as go
    from streamlit.testing.v1 import AppTest

    from src import charts

    db = tmp_path / "theme.db"
    monkeypatch.setenv("TRADE_DB_PATH", str(db))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert any("th-dark" in m.value for m in at.markdown)
    at.button(key="lp_theme_toggle").click().run()
    assert not at.exception
    assert any("th-light" in m.value for m in at.markdown)
    assert database.get_settings(database.get_engine(db))["ui_theme"] == "light"
    restarted = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    restarted.run()
    assert any("th-light" in m.value for m in restarted.markdown)

    fig = go.Figure(go.Bar(x=[1, 2], y=[3, 4], marker_color=charts.NAVY))
    dark = charts.darken(fig)
    assert dark.layout.plot_bgcolor == "#0F1E2D"
    assert dark.data[0].marker.color == charts.DARK_SWAP[charts.NAVY]
    assert fig.data[0].marker.color == charts.NAVY


def test_annual_and_monthly_datasets_side_by_side(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    annual = write_csv(tmp_path, synthetic_rows() + synthetic_rows(flow="M", scale=0.5), "annual.csv")
    monthly_rows = []
    for row in synthetic_rows(years=range(2021, 2023)) + synthetic_rows(flow="M", years=range(2021, 2023), scale=0.5):
        for m in range(1, 13):
            monthly_rows.append(row | {"freqCode": "M", "refMonth": m, "period": row["refYear"] * 100 + m, "primaryValue": row["primaryValue"] / 12})
    monthly = write_csv(tmp_path, monthly_rows, "monthly.csv")
    db = tmp_path / "freq.db"
    eng = database.init_db(database.get_engine(db))
    assert di.import_file(eng, annual)["status"] == "imported"
    assert di.import_file(eng, monthly)["status"] == "imported"
    obs = database.load_observations(eng)
    assert set(obs["frequency"]) == {"A", "M"}
    assert obs[obs["frequency"] == "M"]["month"].nunique() == 12
    monkeypatch.setenv("TRADE_DB_PATH", str(db))
    for freq in ("A", "M"):
        for page in ("views/home.py", "views/trade_explorer.py", "views/trade_mirror.py"):
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
            at.session_state["f_freq"] = freq
            at.switch_page(page).run()
            assert not at.exception, (freq, page)
            assert [r.value for r in at.sidebar.radio if r.label == "Frequency"] == [freq]
            labels = [s.label for s in at.sidebar.select_slider] + [s.label for s in at.sidebar.slider]
            assert ("Period (month and year)" in labels) == (freq == "M")
            if page == "views/home.py":
                imports_card = [m for m in at.metric if "Imports" in m.label]
                assert imports_card and imports_card[0].value != "not available"
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["f_freq"] = "M"
    at.session_state["f_period"] = (202106, 202203)
    at.session_state["f_months"] = [1, 2, 3]
    at.switch_page("views/home.py").run()
    assert not at.exception
    assert any("Jun 2021–Mar 2022 (Jan, Feb, Mar only)" in m.value for m in at.markdown)
