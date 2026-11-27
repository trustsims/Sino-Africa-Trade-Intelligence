import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src import config
from src.schema import ComtradeQuery

PREVIEW_LIMIT = 500
_last_call = [0.0]


class ComtradeError(Exception):
    pass


def _session() -> requests.Session:
    retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",), respect_retry_after_header=True)
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def build_request(q: ComtradeQuery, api_key: str | None) -> tuple[str, dict, dict]:
    base = config.COMTRADE_DATA_URL if api_key else config.COMTRADE_PREVIEW_URL
    url = f"{base}/{q.type_code}/{q.freq_code}/{q.classification}"
    params = {
        "reporterCode": q.reporter_code,
        "partnerCode": q.partner_code,
        "period": ",".join(str(p) for p in q.periods),
        "flowCode": q.flow_code,
        "cmdCode": ",".join(q.cmd_codes),
        "partner2Code": "0",
        "customsCode": "C00",
        "motCode": "0",
        "includeDesc": "true",
    }
    if api_key:
        params["maxRecords"] = "250000"
    else:
        params["maxRecords"] = str(PREVIEW_LIMIT)
    headers = {"Ocp-Apim-Subscription-Key": api_key} if api_key else {}
    return url, params, headers


def cache_key(url: str, params: dict) -> str:
    return hashlib.sha256(json.dumps({"url": url, "params": params}, sort_keys=True).encode()).hexdigest()


def _read_cache(key: str) -> dict | None:
    path = config.CACHE_DIR / f"comtrade_{key}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    fetched = datetime.fromisoformat(payload["retrieved_at"])
    if datetime.now(timezone.utc) - fetched > timedelta(hours=config.COMTRADE_CACHE_HOURS):
        return None
    payload["from_cache"] = True
    return payload


def _write_cache(key: str, payload: dict) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (config.CACHE_DIR / f"comtrade_{key}.json").write_text(json.dumps(payload), encoding="utf-8")


def _throttle() -> None:
    wait = config.COMTRADE_MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def fetch(q: ComtradeQuery, api_key: str | None = None, use_cache: bool = True, session: requests.Session | None = None) -> dict:
    api_key = api_key if api_key is not None else config.comtrade_api_key()
    url, params, headers = build_request(q, api_key)
    key = cache_key(url, params)
    if use_cache:
        cached = _read_cache(key)
        if cached is not None:
            return cached
    _throttle()
    sess = session or _session()
    log = config.get_logger("comtrade")
    log.info(
        "Comtrade request %s reporter=%s partner=%s flow=%s periods=%s cmd=%s (key %s)",
        url,
        q.reporter_code,
        q.partner_code,
        q.flow_code,
        params["period"],
        params["cmdCode"],
        "provided" if api_key else "not used",
    )
    try:
        resp = sess.get(url, params=params, headers=headers, timeout=config.COMTRADE_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout as exc:
        raise ComtradeError("UN Comtrade did not respond in time. Try fewer periods or try again later.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise ComtradeError("Could not connect to UN Comtrade. Check your internet connection; the dashboard keeps working with imported data.") from exc
    except requests.exceptions.RetryError as exc:
        raise ComtradeError("UN Comtrade kept refusing requests (rate limit or server error). Wait a few minutes and try again.") from exc
    if resp.status_code in (401, 403):
        raise ComtradeError(f"UN Comtrade rejected the request (HTTP {resp.status_code}). Check that COMTRADE_API_KEY in .env is a valid subscription key.")
    if resp.status_code == 429:
        raise ComtradeError("UN Comtrade rate limit reached (HTTP 429). Wait before sending more requests.")
    if resp.status_code >= 400:
        raise ComtradeError(f"UN Comtrade returned HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise ComtradeError("UN Comtrade returned a response that is not valid JSON.") from exc
    if body.get("error"):
        raise ComtradeError(f"UN Comtrade reported an error: {body['error']}")
    data = body.get("data") or []
    payload = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": url,
        "params": params,
        "authenticated": bool(api_key),
        "count": body.get("count", len(data)),
        "truncated": (not api_key) and len(data) >= PREVIEW_LIMIT,
        "data": data,
        "from_cache": False,
    }
    _write_cache(key, payload)
    return payload


def to_frame(payload: dict) -> pd.DataFrame:
    df = pd.DataFrame(payload.get("data") or [])
    if df.empty:
        return df
    required = {"refYear", "reporterCode", "partnerCode", "flowCode", "cmdCode", "primaryValue"}
    missing = required - set(df.columns)
    if missing:
        raise ComtradeError(f"Unexpected response format; missing fields: {', '.join(sorted(missing))}")
    return df.astype(str).replace({"None": "", "nan": ""})


def payload_bytes(payload: dict) -> bytes:
    return json.dumps({"endpoint": payload["endpoint"], "params": payload["params"], "data": payload["data"]}, sort_keys=True).encode()
