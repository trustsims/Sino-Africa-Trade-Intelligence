# Methodology

## 1. Development framework: Design Science Research Methodology (DSRM)

The project follows the Design Science Research Methodology of Peffers et al. (2007), which structures the creation and evaluation of an IT artefact in six activities. The mapping to this project is:

| DSRM activity | How it is carried out in this project |
|---|---|
| 1. Problem identification and motivation | Zambia–China trade data are published in raw, inconsistent tables that are hard for exporters, analysts and policymakers to interpret; mirror statistics disagree; copper dependence is high and future values are uncertain. |
| 2. Objectives of a solution | Answer RQ1 (patterns and concentration), RQ2 (reliability of reported data) and RQ3 (copper forecasting) through a reproducible, locally runnable decision-support system. |
| 3. Design and development | Modular Python artefact: SQLite/SQLAlchemy storage, validation and cleaning pipeline, analytics, mirror comparison, forecasting and a Streamlit interface. |
| 4. Demonstration | The dashboard is run on the UN Comtrade Zambia–China dataset (and, for testing only, a labelled synthetic dataset). |
| 5. Evaluation | Automated tests (pytest) verify calculations; forecasting models are evaluated out-of-sample with time-ordered backtesting; mirror results are checked for match rates and coverage. |
| 6. Communication | Thesis, executive PDF report, documentation and the demonstration itself. |

Hevner et al. (2004) provide the complementary guideline that a design artefact must be rigorously evaluated for utility, quality and efficacy — reflected here in automated tests and out-of-sample forecast evaluation.

## 2. Data sources and their limitations

* **UN Comtrade** (United Nations Statistics Division) publishes official merchandise trade statistics reported by national customs or statistical authorities, harmonised to US dollars and the Harmonized System (HS).
* Values are as reported by each country and may be **revised** after first publication; imported datasets record their import (and, for API data, retrieval) timestamp.
* Under the IMTS 2010 recommendations, **exports are valued FOB** (free on board) and **imports CIF** (cost, insurance and freight). When a file does not state the valuation basis, the application applies this convention and marks the record as *assumed*.
* Importers record goods by **country of origin**; exporters by **country of last known destination**. This is a major source of mirror asymmetry.
* Some product lines are **confidential or suppressed**, so product-level sums can be lower than the reported TOTAL. The *coverage check* compares the two.

## 3. Data collection and ingestion

1. Files are uploaded (CSV/Excel) or retrieved from the UN Comtrade API (public preview endpoint without a key; data endpoint with a subscription key stored in `.env`).
2. The uploaded file is copied unchanged to `data/raw/uploads/` and every row is stored verbatim in the `raw_records` table. **The original file is never modified.**
3. A SHA-256 hash of the file blocks duplicate imports of the same file.
4. Columns are mapped to the canonical schema (automatically for the Comtrade layout; reviewable and editable by the user).

## 4. Cleaning and normalisation (pipeline v1.0)

| Rule | Description |
|---|---|
| C01 | Source columns renamed to the canonical schema using the stored mapping; constants (e.g. currency) are explicit and recorded. |
| C02 | Numbers parsed; thousands separators removed. Unparseable values are flagged and **never converted to zero**. |
| C03 | Commodity codes kept as text; codes that lost a leading zero (odd length) are left-padded; TOTAL = level 0. |
| C04 | Flows standardised to X (export), M (import), RX (re-export), RM (re-import). |
| C05 | Countries standardised to UN M49 codes (Zambia 894, China 156). |
| C06 | Valuation basis inferred from flow when missing (marked as assumed). |
| C07 | Rows failing error-level checks are excluded from analysis but kept in the raw table and listed in the issue report. |
| C08 | Exact duplicates: first kept. Conflicting duplicates (same key, different values): all excluded for review. |
| C09 | Breakdown rows (transport mode, customs procedure, second partner) excluded when the aggregate row exists. |
| C10 | Raw preservation (see §3). |

Validation checks V01–V15 (row level) and D01–D10 (dataset level) are listed on the Data Management page. Datasets can be **reprocessed** from the stored raw rows, so the full pipeline is reproducible.

## 5. Product classification handling

* Each record keeps its HS **classification version** (e.g. H5 = HS 2017, H6 = HS 2022).
* Codes from different versions are treated as **different products** unless the user records an explicit mapping (with its source, e.g. a WCO correlation table) and chooses a target version. The number of mapped and unmapped codes is displayed.
* All product statistics use **one HS aggregation level** (2, 4 or 6 digits) so a chapter total is never added to its own sub-headings.

## 6. Aggregation and growth

* Values are summed within one currency, one frequency (annual or monthly), one HS level and one reporter–partner–flow series. Exports and imports, and the two reporters' perspectives, are never added together.
* Records present in more than one active dataset are counted once (most recent import).
* **Year-on-year growth**: `g_t = (V_t − V_{t−1}) / V_{t−1} × 100`, only for consecutive years; undefined if `V_{t−1} = 0` or missing.
* **Compound annual growth rate**: `CAGR = (V_end / V_start)^(1/(end − start)) − 1`, defined only when both values are positive.
* Missing years are reported as missing, not as zero.

## 7. Concentration and diversification

For product shares `s_i` (fractions of the series total in a year):

* **HHI** = Σ s_i² (0–1), also shown ×10,000. Bands of 1,500 and 2,500 points follow the 2010 US Horizontal Merger Guidelines and are used purely descriptively.
* **Normalised HHI** = (HHI − 1/N) / (1 − 1/N), comparable across years with different product counts N.
* **CR_k** = share of the k largest products.
* **Effective number of products** = 1 / HHI — the number of equal-sized products giving the same concentration; a better diversification indicator than the raw count.
* The same measures are computed across **HS sections**, showing whether diversification spans different industries.

## 8. Mirror-trade comparison (RQ2)

* Reporter A = Zambia (exports to China, FOB); Partner B = China (imports from Zambia, CIF).
* Records are matched on period, classification version and HS code at one level.
* **Absolute discrepancy** = B − A. **Percentage discrepancy** = (B − A) / A × 100 (undefined when A = 0). **Mirror ratio** = B / A.
* **Match rate** = matched keys / all keys; **value coverage** = matched A value / total A value.
* Unmatched records are listed by side; codes reported under different HS versions are marked *incomparable*. Missing partner observations are **never imputed**.
* Discrepancies are explained by legitimate factors (valuation, timing, origin vs. destination, re-exports, classification, partner attribution, currency conversion, revisions, suppression) and are **not treated as evidence of misreporting**.

## 9. Forecasting (RQ3)

**Series.** Copper ores and concentrates (HS 2603 / 260300) by default; refined copper (HS 7403), Chapter 74, all copper-related codes or custom codes can be selected. Only the most recent uninterrupted stretch of periods is modelled; gaps are reported, not filled.

**Models.**

| Model | Description | Minimum observations |
|---|---|---|
| Naive | ŷ_{T+h} = y_T | 2 |
| Drift | ŷ_{T+h} = y_T + h·(y_T − y_1)/(T − 1) | 3 |
| Seasonal naive (monthly) | ŷ_{T+h} = y_{T+h−m(k+1)}, m = 12 | 24 |
| Linear trend | OLS on a time index | 4 |
| ARIMA(p,d,q) | Order chosen by AICc on a small grid (p ≤ 2, d ≤ 1, q ≤ 1), parameters limited to about one per three observations | 6 annual / 24 monthly |
| SARIMA (monthly) | Small candidate set of seasonal orders chosen by AIC | 36 |

Prediction intervals: analytic formulas for the benchmark methods (Hyndman & Athanasopoulos, *Forecasting: Principles and Practice*), OLS prediction intervals for the trend model and state-space intervals for ARIMA/SARIMA. Lower bounds below zero are truncated at zero (trade values cannot be negative) and this is reported.

**Evaluation design.** Rolling-origin (expanding window), one-step-ahead: for each origin t from the first test index to T−1, every model is fitted on y_1…y_t and forecasts y_{t+1}. All models are scored on the **same** test points; the series is never shuffled. The first test index is the larger of the minimum training size and the most demanding eligible model's requirement.

**Metrics.**

* MAE = mean |e|; RMSE = √mean(e²).
* **MASE** (Hyndman & Koehler, 2006) = mean(|e_t| / q_t), where q_t is the mean absolute one-step (or seasonal) naive difference in the training window at origin t. MASE < 1 beats the naive benchmark.
* **MAPE** = mean |e/y| × 100, computed only for actuals above 1% of the mean absolute actual value; the number of excluded points is reported.

**Model selection.** The model with the lowest out-of-sample MASE (MAE if MASE is undefined) is identified; if a simpler model is within the parsimony tolerance (default 5%), the simpler model is selected. Complexity order: naive/seasonal naive < drift < linear trend < ARIMA < SARIMA.

**Warnings.** Short series (fewer than 15 annual or 36 monthly observations), missing periods, zeros and high volatility (standard deviation of log changes above 0.5) are flagged. With roughly ten annual observations, results are indicative only.

**Reproducibility.** Every run has a SHA-256 hash of the series and settings; runs can be saved with their parameters, metrics and forecasts. All methods are deterministic.

Forecasts are statistical estimates from the historical series alone; they are not guarantees and do not model prices, mine output or policy.

## 10. Reproducibility and provenance

* `datasets` stores file hash, stored copy, column mapping, cleaning summary, pipeline version, import and retrieval timestamps.
* `import_logs` records every import, reprocess, activation change, mapping and deletion.
* `forecast_runs` stores forecasting parameters, metrics and outputs with a data hash.

## 11. Known limitations and assumptions

* Results inherit the coverage, revisions and confidentiality rules of the source statistics.
* Ten annual observations are too few for strong statistical conclusions about forecasting accuracy; differences between models may not be significant.
* HS version mappings are only as reliable as the mapping source the user records.
* Currency conversion is not performed; values are analysed in the reported currency (US dollars for UN Comtrade).
* Descriptive observations generated by the dashboard state what changed, not why.

## References

* Hevner, A. R., March, S. T., Park, J., & Ram, S. (2004). Design science in information systems research. *MIS Quarterly, 28*(1), 75–105. https://doi.org/10.2307/25148625
* Hyndman, R. J., & Athanasopoulos, G. (2021). *Forecasting: Principles and Practice* (3rd ed.). OTexts. https://otexts.com/fpp3/
* Hyndman, R. J., & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *International Journal of Forecasting, 22*(4), 679–688. https://doi.org/10.1016/j.ijforecast.2006.03.001
* Peffers, K., Tuunanen, T., Rothenberger, M. A., & Chatterjee, S. (2007). A design science research methodology for information systems research. *Journal of Management Information Systems, 24*(3), 45–77. https://doi.org/10.2753/MIS0742-1222240302
* United Nations (2011). *International Merchandise Trade Statistics: Concepts and Definitions 2010* (Series M, No. 52, Rev. 3). https://www.un.org/en/development/desa/publications/international-merchandise-trade-statistics-concepts-and-definitions-2010-imts-2010.html
* U.S. Department of Justice & Federal Trade Commission (2010). *Horizontal Merger Guidelines*, §5.3. https://www.justice.gov/atr/horizontal-merger-guidelines-08192010
* United Nations Statistics Division. UN Comtrade Database. https://comtradeplus.un.org/
