# Sino-African Trade Intelligence Dashboard

**A Data Science and Decision Support System for Zambia–China Trade Analytics**

A locally runnable Streamlit application that turns UN Comtrade trade statistics into analysis for three research questions:

| | Research question | Where |
|---|---|---|
| RQ1 | How have Zambia's exports to China evolved, which products dominate, and how concentrated is the basket? | Executive Overview, Trade Explorer, Product Composition |
| RQ2 | How do Zambia-reported exports compare with China-reported imports, and what explains the differences? | Trade Mirror Analysis |
| RQ3 | How accurately can statistical methods forecast copper export values? | Copper Forecasting, Trade Outlook (5–10 yrs) |

Stack: Python · Streamlit · Plotly · pandas/NumPy · statsmodels/scikit-learn · SQLite/SQLAlchemy · Pydantic · ReportLab. No Docker, cloud service or paid API is required.

---

## 1. Requirements

* Windows 10 or 11, VS Code, Git.
* Python **3.10–3.13** (tested on 3.13 with current packages and with the minimum versions in `requirements.txt`). Check yours with `py --version`.
* About 600 MB of disk space for the virtual environment.

## 2. Add the project to your existing repository

Your repository `Sino-Africa-Trade-Intelligence` (initial commit `6f92730`) keeps its history: copy the new files in, review, then commit.

1. Extract the delivered archive **into** your repository folder (the folder that contains `.git`).
2. Files that may already exist: `README.md`, `.gitignore`, `requirements.txt`. If Windows asks, keep a copy of yours and merge the content (your `.gitignore` lines can simply be appended).
3. Your original `inspect_data.py` is not touched; the new inspector lives at `scripts\inspect_data.py`.
4. Put `comtrade_zambia_china_exports.csv` in `data\raw\` (recommended) or leave it in the project root — both locations are detected. The file is only read, never modified.
5. Review and commit:

```powershell
git status
git diff -- README.md .gitignore requirements.txt
git add .
git commit -m "Add trade intelligence dashboard application"
```

## Online demonstration

A read-only copy of the dashboard can be published on Streamlit Community Cloud, with a project page on GitHub Pages (`docs/index.html`). See [DEPLOY.md](DEPLOY.md) for the step-by-step guide. In the online copy, the four UN Comtrade files in `data/raw/` are imported automatically (`TRADE_AUTOLOAD=1`) and uploads and deletions are switched off (`TRADE_READ_ONLY=1`).

## 3. Install and run (PowerShell in VS Code)

```powershell
cd "C:\path\to\Sino-Africa-Trade-Intelligence"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\init_db.py
python scripts\inspect_data.py
python scripts\import_data.py
python -m streamlit run app.py
```

Open **http://localhost:8501** in your browser (`run_dashboard.bat` opens it for you). Stop the app with `Ctrl+C`. The browser is not opened automatically from the command line because `.streamlit/config.toml` sets `headless = true`, which Streamlit Community Cloud needs.

* `scripts\inspect_data.py` profiles the CSV, shows the suggested column mapping and validation results without importing anything.
* `scripts\import_data.py` imports `comtrade_zambia_china_exports.csv` (or a path you pass: `python scripts\import_data.py data\raw\other.csv --name "China imports"`).
* Everything can also be done in the app on the **Data Management** page.

**One-click alternative:** double-click `run_dashboard.bat`. On first use it creates `.venv`, installs packages and initialises the database, then starts the app.

**Next sessions:** `.\.venv\Scripts\Activate.ps1` then `python -m streamlit run app.py`. Imported data persist in `database\trade_intelligence.db`.

### Light and dark mode

Use **☀ Light mode / ☾ Dark mode** in the sidebar (or **☀ LIGHT / ☾ DARK** on the landing page). The whole site switches, including charts, tables, inputs and menus, and the choice is saved in the database so it is kept after a restart. Dark is the default.

### Annual and monthly data

Import annual and monthly Comtrade files side by side; they are never added together. When monthly data are present, the sidebar shows **Frequency: Annual / Monthly**. In Monthly mode, **Period (month and year)** picks the first and last month, and **Months of the year** can keep only certain calendar months (for example Jan–Mar of every year). Forecasting always uses the full monthly series inside the chosen period.

### Mirror analysis needs China's data

Your CSV contains Zambia-reported exports. For RQ2 also import **China-reported imports from Zambia** (reporter 156, partner 894, flow M) at the same HS level — either download it from https://comtradeplus.un.org/ and upload it, or use **Data Management → UN Comtrade API**. Until then the Trade Mirror page explains what is missing instead of estimating it.

### Optional: UN Comtrade API key

Copy `.env.example` to `.env` and set `COMTRADE_API_KEY=...` (free key from https://comtradedeveloper.un.org/). Without a key the public preview endpoint is used (max 500 records per request). The key is never shown, logged or stored in the database.

### Demonstration data

`python scripts\import_data.py --demo` (or the button on Data Management) loads a **synthetic** Zambia/China mirror dataset for demonstrating the workflows. It is labelled on every page and in every report. Deactivate or delete it before analysing real data. Synthetic data are never substituted automatically if your real file fails to load.

## 4. Testing and linting

```powershell
python -m pytest
ruff check .
```

Latest results: **66 tests passed** (Python 3.13, with both current and minimum package versions); `ruff check` clean. The suite covers CSV/Excel import, missing columns, invalid years and values, duplicates, missing values, currency/unit checks, annual totals, YoY growth, rankings, HHI/CR, zero denominators, mirror formulas, unmatched records, classification mismatch, baseline forecasts, short-series and gap warnings, time-ordered backtesting, metrics, reproducibility, database initialisation, persistence across restarts, repeat imports, interrupted-import recovery, API client error handling (mocked), report exports and rendering of every page (Streamlit AppTest). All test data are small synthetic tables labelled `TEST`.

## 5. Project structure

```
Sino-Africa-Trade-Intelligence/
├── app.py                     entry point: page router + global filters
├── run_dashboard.bat          Windows launcher
├── requirements.txt  pyproject.toml (ruff/pytest)  .env.example  .gitignore
├── .streamlit/config.toml     theme, upload limit, telemetry off
├── views/                     one file per page (st.navigation)
│   landing.py (welcome page)  home.py  trade_explorer.py  product_composition.py  trade_mirror.py
│   copper_forecasting.py  trade_outlook.py  data_management.py  reports.py  methodology.py  settings.py
├── src/
│   config.py        paths, settings, logging
│   schema.py        canonical schema, country/HS metadata, Pydantic models
│   database.py      SQLAlchemy models, initialisation, persistence, backup
│   data_ingestion.py  file reading, mapping, import/reprocess
│   data_validation.py validation rules V01–V15, dataset checks D01–D10
│   data_cleaning.py   canonicalisation, cleaning pipeline, HS mappings
│   outlook.py         5- and 10-year projections, copper production scenarios, balance paths
│   trade_analytics.py totals, growth, rankings, concentration, copper, reconciliation
│   mirror_analysis.py mirror comparison
│   forecasting.py     models, rolling-origin evaluation, selection
│   reporting.py       CSV/Excel/PDF
│   comtrade_client.py UN Comtrade API client
│   charts.py  ui.py   Plotly theme and figures; Streamlit helpers
│   landing_visual.py  one-screen landing visuals: Zambia–China map (offline SVG), logo, corner patterns
├── scripts/  init_db.py  import_data.py  inspect_data.py  generate_synthetic_demo.py
├── assets/styles.css  dark.css (site-wide dark mode)  landing.css (landing page, both modes)  world_region.json (map outlines: Natural Earth 1:50m, public domain, via world-atlas)
├── data/  raw/ (originals; uploads/ copies)  processed/  samples/  cache/
├── database/  (SQLite file created here)
├── tests/    pytest suite
└── docs/     architecture.md  methodology.md  user_guide.md
```

Pages live in `views/` rather than `pages/` because the app uses `st.navigation` (grouped menu and filters that persist between pages); Streamlit's automatic `pages/` discovery would conflict with it.

## 6. Database and backup

* The database is created automatically at `database\trade_intelligence.db` (`scripts\init_db.py` or first app start). Schema versions are recorded in `schema_version`.
* Back up from **Settings & About → Create backup copy** (writes `database\backups\…db` and offers a download), or stop the app and copy the `.db` file. Restore by stopping the app and copying a backup over `trade_intelligence.db`.
* Imports are atomic: an interrupted import is rolled back and cleaned up at the next start.

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `py` / `python` is not recognized | Install Python from python.org and tick *Add python.exe to PATH*, or use the full path, e.g. `C:\Users\<you>\AppData\Local\Programs\Python\Python313\python.exe -m venv .venv`. Reopen VS Code afterwards. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use Command Prompt: `.venv\Scripts\activate.bat`. In VS Code choose the `.venv` interpreter (Ctrl+Shift+P → *Python: Select Interpreter*). |
| `ModuleNotFoundError` (streamlit, statsmodels, …) | Activate `.venv` first, then `pip install -r requirements.txt`. Check `python -c "import sys; print(sys.executable)"` points into `.venv`. |
| Several Python versions installed | Create the environment with a specific one: `py -3.12 -m venv .venv`. |
| Port 8501 already in use | `python -m streamlit run app.py --server.port 8502`, or close the other Streamlit window. |
| CSV not found by `import_data.py` | Place it in `data\raw\` or the project root, or pass its path. No sample data is used instead. |
| CSV/Excel rejected or many rows excluded | Read the message and the issue report on Data Management (download it as CSV). Check delimiter, header row, that year and value columns are mapped, and that rows have the same number of fields. |
| SQLite initialisation fails / `database is locked` | Make sure the `database` folder is writable and not inside a syncing folder that locks files (OneDrive). Close other programs using the `.db`. As a last resort rename the `.db` file and run `python scripts\init_db.py` again (then re-import). |
| UN Comtrade API errors | No internet / proxy → the app keeps working with imported data. HTTP 401/403 → check `COMTRADE_API_KEY`. HTTP 429 → rate limit; wait and retry. Cached responses are reused for 7 days. |
| `ImportError: cannot import name '_lazywhere'` | statsmodels 0.14.x does not work with SciPy 1.16 or later. Upgrade statsmodels (`python -m pip install -U statsmodels`) or install `scipy<1.16`. |
| Forecasting errors or "could not be estimated" | Ensure `statsmodels` and `scipy` installed (`pip install -r requirements.txt`). Very short or constant series cannot support ARIMA; benchmark models still run, and warnings explain the limits. |
| Chart PNG export message | Use the camera icon on any chart (no extra packages). Server-side export needs `pip install kaleido` and Chrome/Chromium. |
| PDF report button fails | `pip install reportlab`. |
| `Fatal error in launcher` after moving the project | The virtual environment stores absolute paths. Delete `.venv` and recreate it in the new folder: `py -m venv .venv`, activate, `python -m pip install -r requirements.txt`. |
| `streamlit.exe` blocked by "An Application Control policy" | Windows Smart App Control blocks the unsigned launcher. Start the app with `python -m streamlit run app.py` (and use `python -m pip`, `python -m pytest`). |
| First page load takes minutes / page stays white | Do not keep the project in a OneDrive-synced folder. Copy it to a local folder such as `C:\Projects` (excluding `.venv`), recreate `.venv`, and optionally add the folder to Windows Security exclusions. |
| `File does not exist: app.py` | The terminal is in the wrong folder. `cd` into the folder that contains `app.py`, or open that folder in VS Code (*File → Open Folder*). |
| Page looks unchanged after editing code | Press `R` in the browser or restart `python -m streamlit run app.py`. |

## 8. Scope notes and limitations

* **Implemented:** every page and module described above, UN Comtrade connector (preview and subscription endpoints, retries, rate-limit spacing, caching, provenance), reproducible cleaning pipeline, persistent storage, exports and PDF reports.
* **Not implemented (optional items):** a World Bank connector (not needed by RQ1–RQ3) and a separate FastAPI service (see `docs/architecture.md`).
* The UN Comtrade connector was tested against mocked responses; live calls could not be made from the build environment, so verify one small query on your machine.
* About ten annual observations support only indicative forecasting conclusions; the app states this whenever it applies.
* See `docs/methodology.md` for formulas, assumptions and references.
