# Architecture

## Overview

The system is a single-process Python application. Streamlit renders the user interface; all logic lives in a plain-Python service layer (`src/`) that can be tested without the UI; SQLite stores data and results.

```
            ┌───────────────────────────── Streamlit UI ─────────────────────────────┐
 Browser ⇄  │ app.py (router + global sidebar filters)                               │
            │ views/: home · trade_explorer · product_composition · trade_mirror ·   │
            │         copper_forecasting · data_management · reports ·              │
            │         methodology · settings                                         │
            └──────────────┬──────────────────────────────────────────────┬──────────┘
                           │ src/ui.py (context, filters, caching)        │ src/charts.py (Plotly)
            ┌──────────────▼──────────────────────────────────────────────▼──────────┐
            │ Service layer                                                          │
            │  data_ingestion → data_cleaning → data_validation   (import pipeline)   │
            │  trade_analytics · mirror_analysis · forecasting     (analytics)        │
            │  reporting (CSV/Excel/PDF) · comtrade_client (UN Comtrade API)          │
            │  schema (canonical fields, Pydantic models) · config                   │
            └──────────────┬─────────────────────────────────────────────────────────┘
                           │ SQLAlchemy ORM (parameterised queries)
            ┌──────────────▼──────────────┐     ┌───────────────────────────────┐
            │ SQLite database/            │     │ Files: data/raw (originals),  │
            │ trade_intelligence.db       │     │ data/raw/uploads (copies),    │
            └─────────────────────────────┘     │ data/processed, data/cache    │
                                                └───────────────────────────────┘
```

**Why no separate API server?** All users of the artefact run it locally, a single Python process is easier to install and defend, and the service layer is already UI-independent (it is exercised directly by the tests). A FastAPI layer would add a second process and deployment step without serving any research question, so it was deliberately not added.

## Request flow

1. `app.py` sets up the page, registers pages with `st.navigation`, and calls `ui.build_context()`.
2. `build_context()` loads active observations from SQLite (cached by a *data version* string that changes on every import, activation change or mapping), removes records duplicated across datasets, renders the global filters and returns a `Context` object holding the scoped, filtered and level-specific frames.
3. The selected page reads the context, calls service functions and renders charts and tables.

Because the filters are rendered by the entry script on every run, their state persists while moving between pages; **Reset filters** clears them.

## Import pipeline

```
file/API → read_table (encoding, delimiter, size, type checks)
         → suggest_mapping / user mapping (ColumnMapping, Pydantic)
         → canonicalize (types, codes, flows, countries, valuation)
         → row_issues (V01–V10, V14–V15) → duplicate_issues (V11–V12) → breakdown_issues (V13)
         → dataset_checks (D01–D10) → clean frame + issue report + summary
         → write_dataset (one transaction: dataset, raw_records, trade_observations, products, import log)
```

A dataset is written with status `importing` and switched to `complete` in the same transaction. If the process stops mid-import, the transaction is rolled back; any record left in `importing` state is cleaned up at the next start-up.

## Database schema

| Table | Purpose | Key constraints |
|---|---|---|
| `schema_version` | Versioned schema initialisation | PK version |
| `data_sources` | Source registry (UN Comtrade, user upload, synthetic) | unique name |
| `datasets` | One row per import: file hash, stored copy, mapping, cleaning summary, pipeline version, synthetic/active flags, timestamps | unique `file_hash` |
| `raw_records` | Every source row unchanged (JSON) | FK dataset, cascade |
| `trade_observations` | Canonical analytical records | unique (`dataset_id`, `record_key`); indexes on year, HS code, reporter/partner/flow, dataset |
| `products` | HS code metadata per classification version | PK (`hs_code`, `classification`) |
| `classification_mappings` | User-recorded HS version mappings with source | unique (from version, from code, to version) |
| `import_logs` | Audit trail of imports, reprocessing, activation, mappings, deletions | — |
| `forecast_runs` | Saved forecasts: parameters, metrics, outputs, data hash, dataset ids | — |
| `app_settings` | Persistent preferences | PK key |

`record_key` = reporter | partner | flow | period | classification | HS code | transport mode | customs procedure | second partner.

## Caching

* `st.cache_resource`: the SQLAlchemy engine (one per database path).
* `st.cache_data`: loaded observations (keyed by data version) and forecasting runs (keyed by series values and settings).
* `data/cache/`: UN Comtrade API responses (default lifetime 7 days, `COMTRADE_CACHE_HOURS`).

## Security and reliability

* Uploads: extension allow-list, size limit (`MAX_UPLOAD_MB`), strict parsing (row-length mismatches are rejected), content is never executed.
* All database access goes through SQLAlchemy with bound parameters.
* Secrets come only from environment variables / `.env` (git-ignored); the API key is never logged or stored.
* Original files are read-only to the application; copies go to `data/raw/uploads/`.
* Logs: `logs/app.log` (rotating).
