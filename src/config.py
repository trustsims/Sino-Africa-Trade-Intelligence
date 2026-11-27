import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")

APP_TITLE = "Sino-African Trade Intelligence Dashboard"
APP_SUBTITLE = "A Data Science and Decision Support System for Zambia–China Trade Analytics"
APP_VERSION = "1.0.0"
PIPELINE_VERSION = "1.0"
SCHEMA_VERSION = 1

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
UPLOAD_DIR = RAW_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLES_DIR = DATA_DIR / "samples"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = PROJECT_ROOT / "logs"
ASSETS_DIR = PROJECT_ROOT / "assets"
DEFAULT_DB_PATH = PROJECT_ROOT / "database" / "trade_intelligence.db"

PRIMARY_DATASET_NAME = "comtrade_zambia_china_exports.csv"
SYNTHETIC_SAMPLE_FILE = SAMPLES_DIR / "SYNTHETIC_demo_zambia_china_mirror.csv"

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MIN_VALID_YEAR = 1962

COMTRADE_API_KEY_ENV = "COMTRADE_API_KEY"
COMTRADE_DATA_URL = "https://comtradeapi.un.org/data/v1/get"
COMTRADE_PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview"
COMTRADE_MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("COMTRADE_MIN_INTERVAL", "1.5"))
COMTRADE_TIMEOUT_SECONDS = int(os.getenv("COMTRADE_TIMEOUT", "60"))
COMTRADE_CACHE_HOURS = int(os.getenv("COMTRADE_CACHE_HOURS", "168"))

DEMO_DATASETS = (
    ("zm_exports_to_china_ag6.csv", "Zambia exports to China (AG6+TOTAL)"),
    ("cn_imports_from_zambia_ag6.csv", "China imports from Zambia (AG6+TOTAL)"),
    ("zm_imports_from_china_ag6.csv", "Zambia imports from China (AG6+TOTAL)"),
    ("cn_exports_to_zambia_ag6.csv", "China exports to Zambia (AG6+TOTAL)"),
)


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def autoload_enabled() -> bool:
    return _flag("TRADE_AUTOLOAD")


def read_only() -> bool:
    return _flag("TRADE_READ_ONLY")


COPPER_ORE_CODE = "260300"
COPPER_RELATED_PREFIXES = ("2603", "74")

DEFAULT_SETTINGS = {
    "display_scale": "Million USD",
    "top_n": 10,
    "forecast_min_train": 5,
    "forecast_interval_level": 95,
    "parsimony_tolerance_pct": 5.0,
    "mape_epsilon_share": 0.01,
    "volatility_warning_threshold": 0.5,
}


def db_path() -> Path:
    override = os.getenv("TRADE_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


def comtrade_api_key() -> str | None:
    key = os.getenv(COMTRADE_API_KEY_ENV, "").strip()
    return key or None


def ensure_directories() -> None:
    for d in (RAW_DIR, UPLOAD_DIR, PROCESSED_DIR, SAMPLES_DIR, CACHE_DIR, LOG_DIR, db_path().parent):
        d.mkdir(parents=True, exist_ok=True)


_LOGGER_READY = False


def get_logger(name: str = "trade_intel") -> logging.Logger:
    global _LOGGER_READY
    logger = logging.getLogger("trade_intel")
    if not _LOGGER_READY:
        ensure_directories()
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
        _LOGGER_READY = True
    return logger if name == "trade_intel" else logger.getChild(name)
