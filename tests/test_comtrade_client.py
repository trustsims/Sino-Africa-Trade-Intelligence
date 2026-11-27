import pytest
import requests
from pydantic import ValidationError

from src import comtrade_client as ct
from src import config
from src import data_ingestion as di
from src.schema import ComtradeQuery


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if self.exc:
            raise self.exc
        return self.response


ROWS = [
    {
        "refYear": 2022,
        "reporterCode": 894,
        "partnerCode": 156,
        "flowCode": "X",
        "cmdCode": "260300",
        "cmdDesc": "TEST ore",
        "primaryValue": 1000.0,
        "classificationCode": "H6",
        "motCode": 0,
        "customsCode": "C00",
        "partner2Code": 0,
    }
]


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "COMTRADE_MIN_SECONDS_BETWEEN_CALLS", 0.0)


def query(**kw):
    base = {"reporter_code": "894", "partner_code": "156", "flow_code": "X", "periods": [2022], "cmd_codes": ["260300"]}
    return ComtradeQuery(**(base | kw))


def test_query_validation():
    with pytest.raises(ValidationError):
        query(flow_code="Z")
    with pytest.raises(ValidationError):
        query(periods=[1900])
    with pytest.raises(ValidationError):
        query(cmd_codes=["26;DROP"])
    with pytest.raises(ValidationError):
        query(freq_code="M", periods=[2022])
    assert query(freq_code="M", periods=[202201, 202202]).periods == [202201, 202202]


def test_request_building_preview_and_key():
    url, params, headers = ct.build_request(query(), None)
    assert url.startswith(config.COMTRADE_PREVIEW_URL) and url.endswith("/C/A/HS") and headers == {}
    assert params["reporterCode"] == "894" and params["cmdCode"] == "260300" and params["maxRecords"] == "500"
    url, params, headers = ct.build_request(query(), "secret")
    assert url.startswith(config.COMTRADE_DATA_URL) and headers == {"Ocp-Apim-Subscription-Key": "secret"}
    assert "secret" not in str(params)


def test_fetch_normalise_cache_and_import(engine):
    sess = FakeSession(FakeResponse(200, {"count": 1, "data": ROWS}))
    payload = ct.fetch(query(), api_key="", session=sess)
    assert payload["count"] == 1 and not payload["from_cache"] and len(sess.calls) == 1
    again = ct.fetch(query(), api_key="", session=sess)
    assert again["from_cache"] and len(sess.calls) == 1
    frame = ct.to_frame(payload)
    mapping = di.suggest_mapping(frame.columns)
    out = di.import_table(engine, frame, mapping, dataset_name="api", file_name="api.json", content=ct.payload_bytes(payload), store_copy=False)
    assert out["status"] == "imported" and out["summary"]["clean_rows"] == 1


@pytest.mark.parametrize("status,match", [(401, "rejected"), (429, "rate limit"), (500, "HTTP 500")])
def test_http_errors(status, match):
    with pytest.raises(ct.ComtradeError, match=match):
        ct.fetch(query(), api_key="k", use_cache=False, session=FakeSession(FakeResponse(status, {"error": "x"})))


def test_network_errors_and_bad_payload():
    with pytest.raises(ct.ComtradeError, match="connect"):
        ct.fetch(query(), api_key="k", use_cache=False, session=FakeSession(exc=requests.exceptions.ConnectionError()))
    with pytest.raises(ct.ComtradeError, match="in time"):
        ct.fetch(query(), api_key="k", use_cache=False, session=FakeSession(exc=requests.exceptions.Timeout()))
    with pytest.raises(ct.ComtradeError, match="missing fields"):
        ct.to_frame({"data": [{"refYear": 2022}]})


def test_preview_truncation_flag():
    rows = ROWS * ct.PREVIEW_LIMIT
    payload = ct.fetch(query(), api_key="", use_cache=False, session=FakeSession(FakeResponse(200, {"count": len(rows), "data": rows})))
    assert payload["truncated"]
