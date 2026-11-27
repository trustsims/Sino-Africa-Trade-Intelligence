import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def synthetic_rows(reporter=894, partner=156, flow="X", years=range(2018, 2023), codes=None, scale=1.0):
    codes = codes or [("260300", "TEST copper ore", 100.0), ("740311", "TEST cathodes", 300.0), ("120740", "TEST seeds", 10.0)]
    rows = []
    for i, y in enumerate(years):
        for code, desc, base in codes:
            rows.append(
                {
                    "refYear": y,
                    "reporterCode": reporter,
                    "partnerCode": partner,
                    "flowCode": flow,
                    "classificationCode": "H5",
                    "cmdCode": code,
                    "cmdDesc": desc,
                    "primaryValue": (base + 10 * i) * scale,
                    "netWgt": base * 2,
                    "qtyUnitAbbr": "kg",
                }
            )
    return rows


@pytest.fixture
def synthetic_df():
    return pd.DataFrame(synthetic_rows())


@pytest.fixture
def mirror_df():
    a = synthetic_rows(894, 156, "X")
    b = synthetic_rows(156, 894, "M", scale=1.1)
    return pd.DataFrame(a + b)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    from src import config, database

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path / "processed")
    eng = database.init_db(database.get_engine(tmp_path / "test.db"))
    yield eng
    eng.dispose()


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
