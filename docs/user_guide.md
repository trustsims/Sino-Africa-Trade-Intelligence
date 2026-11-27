# User Guide

## 1. First start

1. Start the app (`streamlit run app.py` or double-click `run_dashboard.bat`). It opens at http://localhost:8501.
2. If no data is loaded, every page shows an empty-state message. Open **Data Management**.
3. If `comtrade_zambia_china_exports.csv` is in `data/raw/` or the project root, a button offers to import it with the automatic Comtrade mapping. Otherwise upload it.

## 2. Global filters (sidebar)

| Filter | Effect |
|---|---|
| Frequency | Annual or monthly (shown only if both exist). They are never summed together. |
| Currency / Display unit | Values are analysed in one currency; the display unit only changes formatting. |
| Classification versions | Shown when several HS versions exist: keep them separate, or map to a target version using recorded mappings. |
| Years | Period for all KPIs, charts and tables. |
| Reporter / Partner / Trade flow | Which records are included. Empty = all. |
| Product level | HS 2-, 4- or 6-digit (or totals). All product statistics use one level. |
| HS section / chapter / products | Narrow the product scope. |

**Reset filters** restores defaults (Zambia as reporter, exports). **Refresh data** reloads from the database.

The grey bar at the top of each page shows the active datasets, period, level, units, source and load time. A yellow banner appears whenever synthetic data are active.

## 3. Pages

* **Executive Overview** — KPIs for a focus reporter/partner (exports, imports, balance, growth, copper value and share, product count, coverage and warnings), trend and growth charts, top products, composition by HS section, copper trend, automatically calculated observations and a TOTAL coverage check.
* **Trade Explorer** — Trends with CAGR and YoY tables; product rankings (top 10/20/50) and product comparison; stacked composition by section, chapter or product (value or share); year × product heatmap; scatter of product indicators (value, share, CAGR, volatility, weight, unit value); searchable record table with CSV/Excel download. Use *Series for product tabs* in the sidebar to choose which reporter/flow the product tabs analyse.
* **Product Composition** — Top products, single-product trends with unit values, chapter/heading/section summaries, copper breakdown, HHI/CR/effective-number concentration with plain-language guidance, and the classification-mapping workflow.
* **Trade Mirror Analysis** — Choose reporter A and partner B. When both sides are loaded, see match rate, value coverage, aggregate and median discrepancies, annual chart, record-level scatter, largest product discrepancies, matched/unmatched records and downloads. If one side is missing the page explains what to import; nothing is estimated.
* **Copper Forecasting** — Choose reporter, partner, flow and product series (HS 2603 by default). Adjust horizon, interval, minimum training size and parsimony tolerance in *Model settings*. Read the warnings, the selection reason and the out-of-sample comparison table; overlay other models; download forecasts; save runs.
* **Data Management** — Upload & import (preview, column profile, mapping, validation, issue report, overlap check), dataset management (activate/deactivate, reprocess, download cleaned data, delete), UN Comtrade API retrieval, raw vs cleaned comparison, import history and the documented cleaning rules.
* **Reports & Exports** — Filtered records, an analytical Excel workbook, mirror and forecast CSVs, chart PNGs and an executive PDF report reflecting current filters.
* **Methodology & Data Quality** — Data-quality checks of the active data (dataset checks, completeness, coverage heatmap) and the full methodology with formulas and references.
* **Settings & About** — Default display unit, top-N, forecasting defaults, database backup, API key status and environment versions.

## 4. Typical workflows

**RQ1 – patterns and concentration.** Overview → Trade Explorer (Trends, Rankings) → Product Composition (Concentration). Compare HHI and the effective number of products over time, at product and section level.

**RQ2 – mirror statistics.** Import Zambia-reported exports and China-reported imports (Data Management; the API tab can retrieve China's imports with reporter 156, partner 894, flow Import). Then open Trade Mirror Analysis. Read the methodology panel before interpreting differences.

**RQ3 – forecasting.** Copper Forecasting → HS 2603 series → note warnings → compare MASE across models → save the run → include in the PDF report.

## 5. Synthetic demonstration data

*Data Management → Datasets → Import synthetic demo dataset* (or `python scripts\import_data.py --demo`) loads artificial Zambia- and China-reported records so the mirror and forecasting workflows can be demonstrated. They are flagged everywhere and must be deactivated or deleted before analysing real data.
