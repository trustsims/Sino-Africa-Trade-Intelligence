from pathlib import Path

from src import config, database
from src import data_ingestion as di


def pending_files(engine, raw_dir: Path | None = None) -> list[tuple[Path, str]]:
    raw_dir = raw_dir or config.RAW_DIR
    existing = database.list_datasets(engine)
    names = set(existing["name"]) if not existing.empty else set()
    out = []
    for fname, label in config.DEMO_DATASETS:
        path = raw_dir / fname
        if path.exists() and label not in names:
            out.append((path, label))
    return out


def autoload(engine, raw_dir: Path | None = None) -> list[dict]:
    results = []
    for path, label in pending_files(engine, raw_dir):
        try:
            out = di.import_file(engine, path, dataset_name=label)
            results.append({"file": path.name, "status": out.get("status"), "message": out.get("message")})
        except di.IngestionError as exc:
            results.append({"file": path.name, "status": "failed", "message": str(exc)})
            config.get_logger().warning("Automatic import of %s failed: %s", path.name, exc)
    return results
