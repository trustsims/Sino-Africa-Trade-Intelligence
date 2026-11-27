from datetime import datetime

import pandas as pd
import streamlit as st

from src import charts, ui
from src import forecasting as fcst
from src import mirror_analysis as mi
from src import trade_analytics as ta
from src.reporting import OptionalDependencyError, build_pdf_report, fig_to_png, to_csv_bytes, to_excel_bytes
from src.schema import ForecastConfig


@st.cache_data(show_spinner="Preparing default copper forecast…", max_entries=16)
def default_forecast(index: tuple, values: tuple, frequency: str, min_train: int) -> dict:
    idx = list(index) if frequency == "A" else pd.PeriodIndex(list(index), freq="M")
    return fcst.run_forecast(pd.Series(list(values), index=idx, dtype=float), frequency, ForecastConfig(horizon=3, min_train=min_train))


c = ui.ctx()
ui.page_header("Reports & Exports", "Download data, analytical tables, charts and an executive PDF report for the current filters.")
ui.scope_banner(c)
if not c.has_data:
    ui.empty_state()
    st.stop()
lv = c.level_df
if lv.empty:
    st.warning("No records match the current filters.")
    st.stop()

series_df, series_label = ui.series_picker(lv, "rp_series", label="Focus series for product tables and the PDF report")
st.caption(f"Report focus: {series_label}")
filters = ui.describe_filters(c)
stamp = datetime.now().strftime("%Y%m%d_%H%M")
annual = ta.annual_totals(lv)
rank = ta.product_ranking(series_df) if c.level else pd.DataFrame()
conc = ta.concentration_by_year(series_df) if c.level else pd.DataFrame()
sections = ta.group_summary(series_df, "section") if c.level else pd.DataFrame()
cop = ta.copper_breakdown(series_df) if c.level else {"available": False}
rec = ta.reconciliation(c.apply(c.scope), c.level)

a_code, b_code = "894", "156"
mirror_base = c.apply(c.scope, skip=("reporters", "partners", "flows"))
mirror = mi.mirror_compare(mirror_base, a_code, b_code, c.level or 0, "exports")
mirror_ok = mirror["status"] == "ok"

fc_state = st.session_state.get("forecast_result")
if fc_state is None and c.level and c.level >= 4:
    fc_base = c.apply(c.scope, skip=("reporters", "partners", "flows", "months"))
    sub = fc_base[
        (fc_base["reporter_code"] == a_code)
        & (fc_base["partner_code"] == b_code)
        & (fc_base["flow"] == "X")
        & (fc_base["hs_level"] == c.level)
        & (fc_base["hs_code"].str.startswith("2603"))
    ]
    if not sub.empty:
        fq = c.filters.get("frequency", "A")
        s = fcst.build_series(sub, fq)
        res = default_forecast(
            tuple(str(i) if fq == "M" else int(i) for i in s.index), tuple(float(v) for v in s.values), fq, int(c.settings.get("forecast_min_train", 5)) if fq == "A" else 24
        )
        if res.get("status") in ("ok", "unvalidated"):
            fc_state = {
                "label": "Zambia → China exports, copper ores and concentrates (HS 2603), default settings",
                "result": res,
                "cfg": ForecastConfig(horizon=3, min_train=int(c.settings.get("forecast_min_train", 5)) if fq == "A" else 24),
            }

st.subheader("1 · Filtered records")
cols = [
    "dataset_name",
    "reporter_name",
    "partner_name",
    "flow",
    "period",
    "classification",
    "hs_code",
    "product_description",
    "trade_value",
    "currency",
    "net_weight_kg",
    "quantity",
    "quantity_unit",
    "valuation_basis",
    "data_source",
    "quality_flags",
]
ui.download_buttons(lv[cols], f"filtered_records_{stamp}", "rp_rec", "records")
st.caption(f"{len(lv):,} records at {ta.level_label(c.level)}.")

st.subheader("2 · Analytical tables (Excel workbook)")
sheets = {
    "Annual totals": annual,
    "Product ranking": rank,
    "Concentration": conc,
    "HS sections": sections,
    "Copper": cop.get("table") if cop.get("available") else None,
    "TOTAL reconciliation": rec if not rec.empty else None,
}
if mirror_ok:
    sheets.update({"Mirror annual": mirror["annual"], "Mirror by product": mirror["by_product"], "Mirror records": mirror["records"]})
if fc_state:
    r = fc_state["result"]
    sheets.update({"Forecast metrics": r["metrics"], "Forecasts": r["forecasts"], "Backtest": r["backtest"]})
meta = {
    "Generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "Focus series": series_label,
    **filters,
    "Synthetic data present": "YES - not real statistics" if c.synthetic else "No",
}
st.download_button(
    "Download analytical workbook (.xlsx)", to_excel_bytes(sheets, meta), f"trade_analytics_{stamp}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
st.caption("Sheets: " + ", ".join(k for k, v in sheets.items() if v is not None))

st.subheader("3 · Mirror and forecast results")
m1, m2 = st.columns(2)
if mirror_ok:
    m1.download_button("Mirror discrepancy results (CSV)", to_csv_bytes(mirror["records"]), f"mirror_discrepancies_{stamp}.csv", "text/csv")
else:
    m1.info("Mirror results need both Zambia- and China-reported data.")
if fc_state:
    m2.download_button("Forecast results (CSV)", to_csv_bytes(fc_state["result"]["forecasts"]), f"forecasts_{stamp}.csv", "text/csv")
    m2.caption(f"Forecast: {fc_state['label']}")
else:
    m2.info("Run a forecast on the Copper Forecasting page to include it.")

st.subheader("4 · Chart images (PNG)")
chart_opts = {"Annual trend": lambda: charts.trend_lines(annual, c.scale, c.unit)}
if not rank.empty:
    chart_opts["Top products"] = lambda: charts.ranking_bar(rank.head(10), c.scale, c.unit, "Top 10 products")
if not conc.empty:
    chart_opts["Concentration"] = lambda: charts.concentration_chart(conc)
if mirror_ok:
    chart_opts["Mirror comparison"] = lambda: charts.mirror_bars(mirror["annual"], mirror["a_label"], mirror["b_label"], c.scale, c.unit)
pick = st.selectbox("Chart", list(chart_opts))
fig = chart_opts[pick]()
ui.chart(fig)
if st.button("Prepare PNG file"):
    try:
        png = fig_to_png(fig)
        st.download_button("Download PNG", png, f"{pick.lower().replace(' ', '_')}_{stamp}.png", "image/png")
    except OptionalDependencyError as exc:
        st.info(str(exc))
st.caption("Tip: every chart in the app has a camera icon (top-right toolbar) that downloads a PNG without extra packages.")

st.subheader("5 · Executive PDF report")
st.caption(
    "Includes scope and filters, key indicators, calculated findings, trends, top products, concentration, mirror comparison, the latest "
    "forecast, methodology, limitations and sources. Every number is calculated from the active data."
)
if st.button("Generate PDF report", type="primary"):
    focus = series_df
    fy = focus.groupby("year")["trade_value"].sum().sort_index()
    g = ta.yoy_growth(fy)
    kpis = [
        ("Focus series", series_label),
        ("Total value, selected period", c.fmt(fy.sum(), 2)),
        ("Latest annual growth", ui.pct(g.iloc[-1]) if len(g) else "n/a"),
        ("Products at selected level", f"{focus.groupby(['classification', 'hs_code']).ngroups:,}" if c.level else "n/a"),
    ]
    if cop.get("available") and cop.get("ore_available"):
        t = cop["table"]
        kpis.append(("Copper ores & concentrates (HS 2603) share", ui.pct(t["copper_ore_2603"].sum() / t["total"].sum() * 100, signed=False)))
    if not conc.empty and conc["hhi_points"].notna().any():
        last = conc.dropna(subset=["hhi_points"]).iloc[-1]
        kpis.append((f"HHI {int(last['year'])}", f"{last['hhi_points']:,.0f} ({ta.hhi_band(last['hhi_points'])})"))
    warnings = []
    for summ in c.datasets.loc[c.datasets["is_active"], "cleaning_summary"] if not c.datasets.empty else []:
        if isinstance(summ, dict):
            warnings += [ch["message"] for ch in summ.get("dataset_checks", []) if ch.get("severity") == "warning"]
    fc_ctx = None
    if fc_state:
        r = fc_state["result"]
        cfg = fc_state["cfg"]
        fc_ctx = {
            "label": fc_state["label"],
            "selected": r["selected"],
            "reason": r["selection_reason"],
            "metrics": r["metrics"],
            "table": r["forecasts"][r["forecasts"]["model"] == r["selected"]],
            "level": cfg.interval_level,
            "warnings": r["warnings"],
            "disclaimer": fcst.DISCLAIMER,
        }
    ds_tbl = (
        c.datasets.loc[c.datasets["is_active"], ["id", "name", "source_label", "year_min", "year_max", "row_count_clean", "imported_at"]].copy() if not c.datasets.empty else None
    )
    if ds_tbl is not None:
        ds_tbl["imported_at"] = ds_tbl["imported_at"].astype(str).str[:16]
        ds_tbl.columns = ["ID", "Dataset", "Source", "From", "To", "Records", "Imported (UTC)"]
    with st.spinner("Building PDF…"):
        pdf = build_pdf_report(
            {
                "title": "Zambia–China Trade Intelligence Report",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "filters": {"Focus series": series_label, **filters},
                "datasets": ds_tbl,
                "synthetic": c.synthetic,
                "kpis": kpis,
                "observations": ta.observations(focus, c.unit, c.scale),
                "annual": ta.annual_totals(focus),
                "scale": c.scale,
                "scale_label": c.unit,
                "top_products": rank.head(10) if not rank.empty else None,
                "concentration": conc,
                "mirror": mirror if mirror_ok else None,
                "forecast": fc_ctx,
                "warnings": warnings,
            }
        )
    st.download_button("Download PDF report", pdf, f"trade_intelligence_report_{stamp}.pdf", "application/pdf", type="primary")
