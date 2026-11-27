import csv
import hashlib
import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from src import config, database
from src.data_cleaning import run_pipeline
from src.schema import COLUMN_SYNONYMS, ColumnMapping, normalize_column_name

ALLOWED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".xlsm"}
COMTRADE_SIGNATURE = {"primaryvalue", "refyear", "cmdcode", "reportercode"}


class IngestionError(Exception):
    pass


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)
    return stem[:120] or "upload"


def check_file(name: str, content: bytes) -> None:
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise IngestionError(f"Unsupported file type '{ext}'. Upload a CSV (.csv/.txt) or Excel (.xlsx/.xlsm) file.")
    size_mb = len(content) / (1024 * 1024)
    if size_mb > config.MAX_UPLOAD_MB:
        raise IngestionError(f"File is {size_mb:.1f} MB; the limit is {config.MAX_UPLOAD_MB} MB (set MAX_UPLOAD_MB in .env to change it).")
    if len(content) == 0:
        raise IngestionError("The file is empty.")


def excel_sheets(content: bytes) -> list[str]:
    try:
        return pd.ExcelFile(io.BytesIO(content), engine="openpyxl").sheet_names
    except Exception as exc:
        raise IngestionError(f"Could not open Excel workbook: {exc}") from exc


def parse_delimited(text: str, delim: str) -> tuple[pd.DataFrame, int]:
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim, skipinitialspace=True) if any(c.strip() for c in r)]
    if not rows:
        raise IngestionError("The file is empty.")
    header = rows[0]
    while header and not header[-1].strip():
        header = header[:-1]
    n = len(header)
    if n == 0:
        raise IngestionError("The header row is empty.")
    data = []
    trimmed = 0
    for i, r in enumerate(rows[1:], start=2):
        if len(r) > n:
            if any(c.strip() for c in r[n:]):
                raise IngestionError(f"Line {i} has {len(r)} fields but the header has {n}. Values would be shifted into the wrong columns.")
            r = r[:n]
            trimmed += 1
        elif len(r) < n:
            raise IngestionError(f"Line {i} has {len(r)} fields but the header has {n}. The row is incomplete.")
        data.append(r)
    return pd.DataFrame(data, columns=header, dtype=str), trimmed


def read_table(name: str, content: bytes, sheet: str | int | None = None) -> tuple[pd.DataFrame, dict]:
    check_file(name, content)
    ext = Path(name).suffix.lower()
    info = {"file_name": Path(name).name, "size_bytes": len(content)}
    if ext in (".xlsx", ".xlsm"):
        try:
            df = pd.read_excel(io.BytesIO(content), sheet_name=sheet if sheet is not None else 0, dtype=str, engine="openpyxl", keep_default_na=False)
        except Exception as exc:
            raise IngestionError(f"Could not read Excel file: {exc}") from exc
        info["sheet"] = sheet if sheet is not None else 0
    else:
        df = None
        last_error = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = content.decode(enc)
            except UnicodeDecodeError as exc:
                last_error = exc
                continue
            try:
                sample = text[:20000]
                try:
                    delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                except csv.Error:
                    delim = ","
                df, trimmed = parse_delimited(text, delim)
                info.update({"encoding": enc, "delimiter": delim})
                if trimmed:
                    info["trailing_delimiters_removed"] = trimmed
                break
            except Exception as exc:
                last_error = exc
                df = None
                break
        if df is None:
            raise IngestionError(f"Could not parse CSV file: {last_error}")
    df.columns = [str(c).strip() for c in df.columns]
    if df.columns.duplicated().any():
        raise IngestionError("The file has duplicated column names: " + ", ".join(df.columns[df.columns.duplicated()]))
    df = df.dropna(how="all")
    df = df[~(df.astype(str).apply(lambda c: c.str.strip()).eq("").all(axis=1))].reset_index(drop=True)
    if df.empty:
        raise IngestionError("The file contains a header but no data rows.")
    info["rows"] = int(len(df))
    info["columns"] = list(df.columns)
    return df, info


def is_comtrade_layout(columns) -> bool:
    norm = {normalize_column_name(c) for c in columns}
    return len(COMTRADE_SIGNATURE & norm) >= 3


def suggest_mapping(columns) -> dict:
    norm = {normalize_column_name(c): c for c in columns}
    used = set()
    mapped = {}
    for field, synonyms in COLUMN_SYNONYMS.items():
        for syn in synonyms:
            col = norm.get(syn)
            if col and col not in used:
                mapped[field] = col
                used.add(col)
                break
    constants = {}
    if "currency" not in mapped:
        constants["currency"] = "USD"
    constants["data_source"] = "UN Comtrade" if is_comtrade_layout(columns) else "User upload"
    return {"columns": mapped, "constants": constants}


def column_profile(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        s = df[c].astype(str).str.strip()
        non_blank = s[s != ""]
        numeric = pd.to_numeric(non_blank.str.replace(",", "", regex=False), errors="coerce")
        kind = "numeric" if len(non_blank) and numeric.notna().mean() > 0.95 else "text"
        rows.append(
            {
                "column": c,
                "inferred type": kind,
                "non-blank": int(len(non_blank)),
                "blank": int(len(s) - len(non_blank)),
                "distinct": int(non_blank.nunique()),
                "example": non_blank.iloc[0] if len(non_blank) else "",
            }
        )
    return pd.DataFrame(rows)


def validate_mapping(mapping: dict) -> ColumnMapping:
    return ColumnMapping(**mapping)


def preview_pipeline(raw: pd.DataFrame, mapping: dict, source_label: str) -> dict:
    cm = validate_mapping(mapping)
    return run_pipeline(raw, cm, source_label)


def overlap_report(engine: Engine, clean: pd.DataFrame) -> pd.DataFrame:
    existing = database.load_observations(engine, active_only=False)
    if existing.empty or clean.empty:
        return pd.DataFrame(columns=["dataset_id", "dataset_name", "overlapping_records"])
    keys = set(clean["record_key"])
    ex = existing[existing["record_key"].isin(keys)]
    if ex.empty:
        return pd.DataFrame(columns=["dataset_id", "dataset_name", "overlapping_records"])
    return ex.groupby(["dataset_id", "dataset_name"]).size().reset_index(name="overlapping_records")


def store_upload_copy(name: str, content: bytes, digest: str) -> Path:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.UPLOAD_DIR / f"{digest[:12]}_{safe_name(name)}"
    if not dest.exists():
        dest.write_bytes(content)
    return dest


def import_table(
    engine: Engine,
    raw: pd.DataFrame,
    mapping: dict,
    *,
    dataset_name: str,
    file_name: str,
    content: bytes,
    source_label: str | None = None,
    is_synthetic: bool = False,
    notes: str | None = None,
    retrieved_at: datetime | None = None,
    store_copy: bool = True,
) -> dict:
    digest = file_hash(content)
    existing = database.find_dataset_by_hash(engine, digest)
    if existing and existing["status"] == "complete":
        database.add_log(engine, "import", "skipped", f"Duplicate import of {file_name} blocked (identical to dataset #{existing['id']}).", existing["id"])
        return {"status": "duplicate", "dataset_id": existing["id"], "message": f"This exact file was already imported as dataset #{existing['id']} ('{existing['name']}')."}
    cm = validate_mapping(mapping)
    label = source_label or cm.constants.get("data_source") or "User upload"
    result = run_pipeline(raw, cm, label)
    clean = result["clean"]
    if clean.empty:
        database.add_log(engine, "import", "failed", f"No valid records in {file_name}", details=result["summary"])
        return {"status": "empty", "dataset_id": None, "message": "No records passed validation; nothing was imported.", **result}
    overlap = overlap_report(engine, clean)
    stored = store_upload_copy(file_name, content, digest) if store_copy else None
    src_name = "Synthetic demonstration data" if is_synthetic else ("UN Comtrade" if "comtrade" in label.lower() else "User upload")
    meta = {
        "name": dataset_name,
        "file_name": file_name,
        "file_hash": digest,
        "stored_copy": str(stored.relative_to(config.PROJECT_ROOT)) if stored and stored.is_relative_to(config.PROJECT_ROOT) else (str(stored) if stored else None),
        "source_id": database.source_id(engine, src_name),
        "source_label": label,
        "is_synthetic": is_synthetic,
        "is_active": True,
        "frequency": result["summary"]["frequency"],
        "perspective": result["summary"]["perspective"],
        "row_count_raw": result["summary"]["raw_rows"],
        "row_count_clean": result["summary"]["clean_rows"],
        "row_count_excluded": result["summary"]["excluded_rows"],
        "year_min": result["summary"]["year_min"],
        "year_max": result["summary"]["year_max"],
        "column_mapping": cm.model_dump(),
        "cleaning_summary": result["summary"],
        "pipeline_version": config.PIPELINE_VERSION,
        "retrieved_at": retrieved_at,
        "notes": notes,
    }
    if existing:
        database.delete_dataset(engine, existing["id"])
    raw_rows = raw.astype(str).to_dict("records")
    try:
        ds_id = database.write_dataset(engine, meta, clean, raw_rows)
    except Exception as exc:
        database.add_log(engine, "import", "failed", f"Import of {file_name} failed and was rolled back: {exc}")
        raise
    config.get_logger().info("Imported dataset %s (%s clean rows) from %s", ds_id, len(clean), file_name)
    return {
        "status": "imported",
        "dataset_id": ds_id,
        "overlap": overlap,
        "message": f"Imported {len(clean):,} clean records as dataset #{ds_id}; {result['summary']['excluded_rows']:,} rows excluded (see issue report).",
        **result,
    }


def import_file(
    engine: Engine, path: Path, *, dataset_name: str | None = None, is_synthetic: bool = False, mapping: dict | None = None, sheet=None, notes: str | None = None
) -> dict:
    path = Path(path)
    if not path.exists():
        raise IngestionError(f"File not found: {path}")
    content = path.read_bytes()
    raw, _ = read_table(path.name, content, sheet)
    mapping = mapping or suggest_mapping(raw.columns)
    if is_synthetic:
        mapping.setdefault("constants", {})["data_source"] = "SYNTHETIC demonstration data"
    return import_table(engine, raw, mapping, dataset_name=dataset_name or path.stem, file_name=path.name, content=content, is_synthetic=is_synthetic, notes=notes)


def reprocess_dataset(engine: Engine, dataset_id: int) -> dict:
    ds = database.get_dataset(engine, dataset_id)
    if ds is None:
        raise IngestionError(f"Dataset {dataset_id} not found")
    rows = database.load_raw_records(engine, dataset_id)
    if not rows:
        raise IngestionError("No raw records stored for this dataset; it cannot be reprocessed.")
    raw = pd.DataFrame(rows)
    cm = ColumnMapping(**ds["column_mapping"])
    result = run_pipeline(raw, cm, ds["source_label"] or "User upload")
    database.replace_observations(engine, dataset_id, result["clean"], result["summary"], cm.model_dump())
    return result


def clean_export(engine: Engine, dataset_id: int) -> pd.DataFrame:
    df = database.load_observations(engine, [dataset_id], active_only=False)
    drop = [c for c in ("id", "is_synthetic") if c in df.columns]
    return df.drop(columns=drop)


def write_processed(engine: Engine, dataset_id: int) -> Path:
    df = clean_export(engine, dataset_id)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = config.PROCESSED_DIR / f"dataset_{dataset_id}_clean.csv"
    df.to_csv(out, index=False)
    return out
