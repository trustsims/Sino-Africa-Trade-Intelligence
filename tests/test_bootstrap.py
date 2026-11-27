import pandas as pd

from src import bootstrap, config, database
from tests.conftest import synthetic_rows


def _write_demo(raw_dir, monkeypatch):
    monkeypatch.setattr(config, "DEMO_DATASETS", (("a.csv", "Demo exports"), ("b.csv", "Demo imports")))
    pd.DataFrame(synthetic_rows()).to_csv(raw_dir / "a.csv", index=False)
    pd.DataFrame(synthetic_rows(156, 894, "M", scale=1.1)).to_csv(raw_dir / "b.csv", index=False)


def test_autoload_imports_missing_demo_files_once(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_demo(raw, monkeypatch)
    eng = database.init_db(database.get_engine(tmp_path / "t.db"))
    first = bootstrap.autoload(eng, raw)
    assert [r["file"] for r in first] == ["a.csv", "b.csv"]
    assert len(database.list_datasets(eng)) == 2
    assert bootstrap.autoload(eng, raw) == []
    assert len(database.list_datasets(eng)) == 2


def test_autoload_skips_absent_files(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(config, "DEMO_DATASETS", (("missing.csv", "Missing"),))
    eng = database.init_db(database.get_engine(tmp_path / "t.db"))
    assert bootstrap.autoload(eng, raw) == []
    assert database.list_datasets(eng).empty


def test_flags_read_environment(monkeypatch):
    monkeypatch.delenv("TRADE_AUTOLOAD", raising=False)
    monkeypatch.setenv("TRADE_READ_ONLY", "true")
    assert not config.autoload_enabled()
    assert config.read_only()
