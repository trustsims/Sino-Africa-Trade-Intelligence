import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from src import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    file_name: Mapped[str | None] = mapped_column(String(300))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    stored_copy: Mapped[str | None] = mapped_column(String(500))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    source_label: Mapped[str | None] = mapped_column(String(200))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="importing")
    frequency: Mapped[str | None] = mapped_column(String(10))
    perspective: Mapped[str | None] = mapped_column(String(200))
    row_count_raw: Mapped[int] = mapped_column(Integer, default=0)
    row_count_clean: Mapped[int] = mapped_column(Integer, default=0)
    row_count_excluded: Mapped[int] = mapped_column(Integer, default=0)
    year_min: Mapped[int | None] = mapped_column(Integer)
    year_max: Mapped[int | None] = mapped_column(Integer)
    column_mapping: Mapped[dict | None] = mapped_column(JSON)
    cleaning_summary: Mapped[dict | None] = mapped_column(JSON)
    pipeline_version: Mapped[str | None] = mapped_column(String(20))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notes: Mapped[str | None] = mapped_column(Text)


class RawRecord(Base):
    __tablename__ = "raw_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)


class TradeObservation(Base):
    __tablename__ = "trade_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    record_key: Mapped[str] = mapped_column(String(200))
    reporter_code: Mapped[str | None] = mapped_column(String(10))
    reporter_name: Mapped[str | None] = mapped_column(String(120))
    partner_code: Mapped[str | None] = mapped_column(String(10))
    partner_name: Mapped[str | None] = mapped_column(String(120))
    flow: Mapped[str] = mapped_column(String(4))
    frequency: Mapped[str] = mapped_column(String(1))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int | None] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(10))
    hs_code: Mapped[str] = mapped_column(String(12))
    hs_level: Mapped[int] = mapped_column(Integer)
    chapter: Mapped[str | None] = mapped_column(String(2))
    section: Mapped[str | None] = mapped_column(String(80))
    classification: Mapped[str] = mapped_column(String(10))
    product_description: Mapped[str | None] = mapped_column(Text)
    trade_value: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    net_weight_kg: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float | None] = mapped_column(Float)
    quantity_unit: Mapped[str | None] = mapped_column(String(30))
    valuation_basis: Mapped[str | None] = mapped_column(String(10))
    valuation_assumed: Mapped[bool] = mapped_column(Boolean, default=False)
    data_source: Mapped[str | None] = mapped_column(String(200))
    original_record_id: Mapped[str | None] = mapped_column(String(100))
    quality_flags: Mapped[str | None] = mapped_column(String(300))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint("dataset_id", "record_key", name="uq_obs_dataset_key"),
        Index("ix_obs_year", "year"),
        Index("ix_obs_hs", "hs_code"),
        Index("ix_obs_reporter_partner_flow", "reporter_code", "partner_code", "flow"),
        Index("ix_obs_dataset", "dataset_id"),
    )


class Product(Base):
    __tablename__ = "products"
    hs_code: Mapped[str] = mapped_column(String(12), primary_key=True)
    classification: Mapped[str] = mapped_column(String(10), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)
    hs_level: Mapped[int] = mapped_column(Integer)
    chapter: Mapped[str | None] = mapped_column(String(2))


class ClassificationMapping(Base):
    __tablename__ = "classification_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_classification: Mapped[str] = mapped_column(String(10))
    from_code: Mapped[str] = mapped_column(String(12))
    to_classification: Mapped[str] = mapped_column(String(10))
    to_code: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("from_classification", "from_code", "to_classification", name="uq_mapping"),)


class ImportLog(Base):
    __tablename__ = "import_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    series_label: Mapped[str] = mapped_column(String(300))
    frequency: Mapped[str] = mapped_column(String(1))
    horizon: Mapped[int] = mapped_column(Integer)
    selected_model: Mapped[str | None] = mapped_column(String(60))
    data_hash: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[list | None] = mapped_column(JSON)
    forecast: Mapped[list | None] = mapped_column(JSON)
    warnings: Mapped[list | None] = mapped_column(JSON)
    dataset_ids: Mapped[list | None] = mapped_column(JSON)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | float | int | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


_ENGINES: dict[str, Engine] = {}


def get_engine(path: Path | str | None = None) -> Engine:
    p = Path(path) if path else config.db_path()
    key = str(p.resolve())
    if key not in _ENGINES:
        p.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{p.as_posix()}", future=True)

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        _ENGINES[key] = engine
    return _ENGINES[key]


def dispose_engines() -> None:
    for e in _ENGINES.values():
        e.dispose()
    _ENGINES.clear()


@contextmanager
def session_scope(engine: Engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DEFAULT_SOURCES = [
    ("UN Comtrade", "https://comtradeplus.un.org/", "United Nations Commodity Trade Statistics Database (official merchandise trade statistics reported by national authorities)."),
    ("User upload", None, "File uploaded through the Data Management page or import script."),
    ("Synthetic demonstration data", None, "Artificially generated records for demonstration and testing only. Not real trade statistics."),
]


def init_db(engine: Engine | None = None) -> Engine:
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    with session_scope(engine) as s:
        current = s.scalar(select(func.max(SchemaVersion.version)))
        if current is None or current < config.SCHEMA_VERSION:
            s.add(SchemaVersion(version=config.SCHEMA_VERSION))
        for name, url, desc in DEFAULT_SOURCES:
            if s.scalar(select(DataSource.id).where(DataSource.name == name)) is None:
                s.add(DataSource(name=name, url=url, description=desc))
        stale = s.scalars(select(Dataset).where(Dataset.status == "importing")).all()
        for ds in stale:
            s.execute(delete(TradeObservation).where(TradeObservation.dataset_id == ds.id))
            s.execute(delete(RawRecord).where(RawRecord.dataset_id == ds.id))
            ds.status = "failed"
            ds.is_active = False
            s.add(ImportLog(dataset_id=ds.id, action="recovery", status="failed", message="Interrupted import detected at startup; partial records removed."))
    return engine


def schema_version(engine: Engine) -> int | None:
    with session_scope(engine) as s:
        return s.scalar(select(func.max(SchemaVersion.version)))


def source_id(engine: Engine, name: str) -> int | None:
    with session_scope(engine) as s:
        return s.scalar(select(DataSource.id).where(DataSource.name == name))


def find_dataset_by_hash(engine: Engine, file_hash: str) -> dict | None:
    with session_scope(engine) as s:
        ds = s.scalar(select(Dataset).where(Dataset.file_hash == file_hash))
        return _ds_dict(ds) if ds else None


def _ds_dict(ds: Dataset) -> dict:
    return {c.name: getattr(ds, c.name) for c in Dataset.__table__.columns}


def write_dataset(engine: Engine, meta: dict, observations: pd.DataFrame, raw_rows: list[dict] | None) -> int:
    obs_cols = [c.name for c in TradeObservation.__table__.columns if c.name not in ("id", "dataset_id", "imported_at")]
    with session_scope(engine) as s:
        ds = Dataset(**{k: v for k, v in meta.items() if k in Dataset.__table__.columns}, status="importing")
        s.add(ds)
        s.flush()
        ds_id = ds.id
        now = utcnow()
        if raw_rows:
            batch = [{"dataset_id": ds_id, "row_number": i, "payload": r} for i, r in enumerate(raw_rows)]
            for start in range(0, len(batch), 5000):
                s.execute(insert(RawRecord), batch[start : start + 5000])
        records = _records(observations, obs_cols)
        for r in records:
            r["dataset_id"] = ds_id
            r["imported_at"] = now
        for start in range(0, len(records), 5000):
            s.execute(insert(TradeObservation), records[start : start + 5000])
        _upsert_products(s, observations)
        ds.status = "complete"
        ds.updated_at = now
        s.add(
            ImportLog(
                dataset_id=ds_id,
                action="import",
                status="complete",
                message=f"Imported {len(records)} clean observations from {meta.get('file_name')}",
                details=meta.get("cleaning_summary"),
            )
        )
    return ds_id


def replace_observations(engine: Engine, dataset_id: int, observations: pd.DataFrame, summary: dict, mapping: dict) -> None:
    obs_cols = [c.name for c in TradeObservation.__table__.columns if c.name not in ("id", "dataset_id", "imported_at")]
    with session_scope(engine) as s:
        s.execute(delete(TradeObservation).where(TradeObservation.dataset_id == dataset_id))
        now = utcnow()
        records = _records(observations, obs_cols)
        for r in records:
            r["dataset_id"] = dataset_id
            r["imported_at"] = now
        for start in range(0, len(records), 5000):
            s.execute(insert(TradeObservation), records[start : start + 5000])
        _upsert_products(s, observations)
        s.execute(
            update(Dataset)
            .where(Dataset.id == dataset_id)
            .values(
                row_count_clean=len(records),
                row_count_excluded=summary.get("excluded_rows", 0),
                cleaning_summary=summary,
                column_mapping=mapping,
                pipeline_version=config.PIPELINE_VERSION,
                updated_at=now,
                year_min=summary.get("year_min"),
                year_max=summary.get("year_max"),
                frequency=summary.get("frequency"),
                perspective=summary.get("perspective"),
            )
        )
        s.add(
            ImportLog(
                dataset_id=dataset_id,
                action="reprocess",
                status="complete",
                message=f"Reprocessed dataset with pipeline {config.PIPELINE_VERSION}: {len(records)} clean observations",
                details=summary,
            )
        )


def _records(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    present = [c for c in cols if c in df.columns]
    out = df[present].astype(object).where(df[present].notna(), None).to_dict("records")
    return out


def _upsert_products(s, df: pd.DataFrame) -> None:
    if df.empty:
        return
    prods = df[["hs_code", "classification", "product_description", "hs_level", "chapter"]].drop_duplicates(["hs_code", "classification"])
    existing = {(p.hs_code, p.classification) for p in s.scalars(select(Product)).all()}
    for row in prods.itertuples(index=False):
        if (row.hs_code, row.classification) in existing:
            continue
        desc = row.product_description if isinstance(row.product_description, str) else None
        chapter = row.chapter if isinstance(row.chapter, str) else None
        s.add(Product(hs_code=row.hs_code, classification=row.classification, description=desc, hs_level=int(row.hs_level), chapter=chapter))


def load_raw_records(engine: Engine, dataset_id: int) -> list[dict]:
    with session_scope(engine) as s:
        rows = s.execute(select(RawRecord.payload).where(RawRecord.dataset_id == dataset_id).order_by(RawRecord.row_number)).all()
        return [r[0] for r in rows]


def list_datasets(engine: Engine) -> pd.DataFrame:
    with session_scope(engine) as s:
        rows = [_ds_dict(d) for d in s.scalars(select(Dataset).order_by(Dataset.id)).all()]
    return pd.DataFrame(rows)


def get_dataset(engine: Engine, dataset_id: int) -> dict | None:
    with session_scope(engine) as s:
        ds = s.get(Dataset, dataset_id)
        return _ds_dict(ds) if ds else None


def set_dataset_active(engine: Engine, dataset_id: int, active: bool) -> None:
    with session_scope(engine) as s:
        s.execute(update(Dataset).where(Dataset.id == dataset_id).values(is_active=active, updated_at=utcnow()))
        s.add(ImportLog(dataset_id=dataset_id, action="activate" if active else "deactivate", status="complete"))


def delete_dataset(engine: Engine, dataset_id: int) -> None:
    with session_scope(engine) as s:
        s.execute(delete(TradeObservation).where(TradeObservation.dataset_id == dataset_id))
        s.execute(delete(RawRecord).where(RawRecord.dataset_id == dataset_id))
        s.execute(delete(Dataset).where(Dataset.id == dataset_id))
        s.add(ImportLog(dataset_id=dataset_id, action="delete", status="complete", message="Dataset removed from database"))


def load_observations(engine: Engine, dataset_ids: list[int] | None = None, active_only: bool = True) -> pd.DataFrame:
    obs = TradeObservation.__table__
    dst = Dataset.__table__
    stmt = select(*obs.columns, dst.c.name.label("dataset_name"), dst.c.is_synthetic).select_from(obs.join(dst, dst.c.id == obs.c.dataset_id)).where(dst.c.status == "complete")
    if active_only:
        stmt = stmt.where(dst.c.is_active.is_(True))
    if dataset_ids is not None:
        stmt = stmt.where(obs.c.dataset_id.in_([int(i) for i in dataset_ids]))
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
    cols = [c.name for c in obs.columns] + ["dataset_name", "is_synthetic"]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["trade_value"] = df["trade_value"].astype(float)
        for c in ("net_weight_kg", "quantity"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["year"] = df["year"].astype(int)
        df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int64")
        df["hs_level"] = df["hs_level"].astype(int)
        df["is_synthetic"] = df["is_synthetic"].astype(bool)
    return df


def data_version(engine: Engine) -> str:
    with session_scope(engine) as s:
        n = s.scalar(select(func.count(Dataset.id)))
        latest = s.scalar(select(func.max(Dataset.updated_at)))
        active = s.scalar(select(func.count(Dataset.id)).where(Dataset.is_active.is_(True)))
        maps = s.scalar(select(func.count(ClassificationMapping.id)))
    return f"{n}-{active}-{latest}-{maps}"


def add_log(engine: Engine, action: str, status: str, message: str, dataset_id: int | None = None, details: dict | None = None) -> None:
    with session_scope(engine) as s:
        s.add(ImportLog(dataset_id=dataset_id, action=action, status=status, message=message, details=details))


def import_logs(engine: Engine, limit: int = 200) -> pd.DataFrame:
    with session_scope(engine) as s:
        rows = s.scalars(select(ImportLog).order_by(ImportLog.id.desc()).limit(limit)).all()
        data = [{"id": r.id, "time (UTC)": r.created_at, "dataset_id": r.dataset_id, "action": r.action, "status": r.status, "message": r.message} for r in rows]
    return pd.DataFrame(data)


def list_mappings(engine: Engine) -> pd.DataFrame:
    with session_scope(engine) as s:
        rows = s.scalars(select(ClassificationMapping).order_by(ClassificationMapping.id)).all()
        data = [
            {
                "id": r.id,
                "from_classification": r.from_classification,
                "from_code": r.from_code,
                "to_classification": r.to_classification,
                "to_code": r.to_code,
                "source": r.source,
                "created_at": r.created_at,
            }
            for r in rows
        ]
    return pd.DataFrame(data, columns=["id", "from_classification", "from_code", "to_classification", "to_code", "source", "created_at"])


def add_mapping(engine: Engine, from_cl: str, from_code: str, to_cl: str, to_code: str, source: str) -> None:
    if not source or not source.strip():
        raise ValueError("A mapping source (e.g. WCO correlation table reference) is required")
    for code in (from_code, to_code):
        if not str(code).isdigit() or len(str(code)) not in (2, 4, 6):
            raise ValueError("HS codes must contain 2, 4 or 6 digits")
    if len(str(from_code)) != len(str(to_code)):
        raise ValueError("Mapped codes must be at the same HS level")
    with session_scope(engine) as s:
        existing = s.scalar(
            select(ClassificationMapping).where(
                ClassificationMapping.from_classification == from_cl, ClassificationMapping.from_code == from_code, ClassificationMapping.to_classification == to_cl
            )
        )
        if existing:
            existing.to_code = to_code
            existing.source = source.strip()
        else:
            s.add(ClassificationMapping(from_classification=from_cl, from_code=from_code, to_classification=to_cl, to_code=to_code, source=source.strip()))
        s.add(ImportLog(action="mapping", status="complete", message=f"{from_cl}:{from_code} -> {to_cl}:{to_code} ({source.strip()})"))


def delete_mapping(engine: Engine, mapping_id: int) -> None:
    with session_scope(engine) as s:
        s.execute(delete(ClassificationMapping).where(ClassificationMapping.id == mapping_id))


def save_forecast_run(engine: Engine, run: dict) -> int:
    with session_scope(engine) as s:
        fr = ForecastRun(**{k: v for k, v in run.items() if k in ForecastRun.__table__.columns})
        s.add(fr)
        s.flush()
        return fr.id


def list_forecast_runs(engine: Engine, limit: int = 50) -> pd.DataFrame:
    with session_scope(engine) as s:
        rows = s.scalars(select(ForecastRun).order_by(ForecastRun.id.desc()).limit(limit)).all()
        data = [
            {
                "id": r.id,
                "created_at": r.created_at,
                "series_label": r.series_label,
                "frequency": r.frequency,
                "horizon": r.horizon,
                "selected_model": r.selected_model,
                "data_hash": r.data_hash,
                "parameters": r.parameters,
                "metrics": r.metrics,
                "forecast": r.forecast,
                "warnings": r.warnings,
                "dataset_ids": r.dataset_ids,
            }
            for r in rows
        ]
    return pd.DataFrame(data)


def get_settings(engine: Engine) -> dict:
    out = dict(config.DEFAULT_SETTINGS)
    with session_scope(engine) as s:
        for row in s.scalars(select(AppSetting)).all():
            out[row.key] = row.value
    return out


def set_setting(engine: Engine, key: str, value) -> None:
    with session_scope(engine) as s:
        row = s.get(AppSetting, key)
        if row:
            row.value = value
            row.updated_at = utcnow()
        else:
            s.add(AppSetting(key=key, value=value))


def backup_database(engine: Engine, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_path = engine.url.database
    with sqlite3.connect(src_path) as src, sqlite3.connect(dest) as dst:
        src.backup(dst)
    return dest


def database_file(engine: Engine) -> Path:
    return Path(engine.url.database)


def copy_file(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest
