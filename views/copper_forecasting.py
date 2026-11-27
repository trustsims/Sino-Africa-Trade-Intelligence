import json

import pandas as pd
import streamlit as st

from src import charts, database, ui
from src import forecasting as fcst
from src.schema import FLOW_LABELS, ForecastConfig, country_name

c = ui.ctx()
ui.page_header("Copper Export Forecasting", "Statistical forecasts of copper export values with transparent, time-ordered evaluation.", "RQ3")
ui.scope_banner(c, "Uses the sidebar frequency, year range and product level. Reporter, partner, flow and product are chosen below.")
if not c.has_data:
    ui.empty_state()
    st.stop()


@st.cache_data(show_spinner="Fitting and evaluating models…", max_entries=32)
def cached_forecast(index: tuple, values: tuple, frequency: str, cfg_json: str) -> dict:
    idx = list(index) if frequency == "A" else pd.PeriodIndex(list(index), freq="M")
    s = pd.Series(list(values), index=idx, dtype=float)
    return fcst.run_forecast(s, frequency, ForecastConfig(**json.loads(cfg_json)))


base = c.apply(c.scope, skip=("reporters", "partners", "flows", "sections", "chapters", "products", "months"))
if c.filters.get("months"):
    st.caption("The 'Months of the year' selection is not applied here: forecasting needs the full, unbroken monthly series. The period range still applies.")
level = c.level or 0
freq = c.filters.get("frequency", "A")
reporters = sorted(base["reporter_code"].unique(), key=country_name)
s1, s2, s3 = st.columns(3)
rep = s1.selectbox("Reporter", reporters, index=reporters.index("894") if "894" in reporters else 0, format_func=country_name, key="fc_rep")
partners = sorted(base.loc[base["reporter_code"] == rep, "partner_code"].unique(), key=country_name)
par = s2.selectbox("Partner", partners, index=partners.index("156") if "156" in partners else 0, format_func=country_name, key="fc_par")
flows = [f for f in FLOW_LABELS if f in set(base.loc[(base["reporter_code"] == rep) & (base["partner_code"] == par), "flow"])]
flow = s3.selectbox("Flow", flows, index=flows.index("X") if "X" in flows else 0, format_func=FLOW_LABELS.get, key="fc_flow")
series_base = base[(base["reporter_code"] == rep) & (base["partner_code"] == par) & (base["flow"] == flow) & (base["hs_level"] == level)]

PRODUCT_SETS = {
    "ore": ("Copper ores and concentrates (HS 2603 / 260300)", ("2603",), 4),
    "refined": ("Refined copper, cathodes and other unwrought (HS 7403)", ("7403",), 4),
    "ch74": ("Copper and articles thereof (HS Chapter 74)", ("74",), 2),
    "all": ("All copper-related (HS 2603 + Chapter 74)", ("2603", "74"), 4),
    "custom": ("Custom HS codes", None, 2),
}
choice = st.radio("Product series", list(PRODUCT_SETS), format_func=lambda k: PRODUCT_SETS[k][0], horizontal=True, key="fc_set")
label, prefixes, min_level = PRODUCT_SETS[choice]
if choice == "custom":
    codes = sorted(series_base["hs_code"].unique()) if level > 0 else []
    desc = series_base.dropna(subset=["product_description"]).groupby("hs_code")["product_description"].first()
    default = [x for x in codes if x.startswith(("2603", "74"))][:3]
    picked = st.multiselect("Codes to include (summed)", codes, default=default, format_func=lambda x: f"{x} – {str(desc.get(x, ''))[:60]}", key="fc_codes")
    prefixes = tuple(picked)
    label = "Custom: " + ", ".join(picked) if picked else "Custom"
if level == 0:
    st.warning("Copper cannot be isolated from all-commodity totals. Select an HS product level in the sidebar.")
    st.stop()
if level < min_level:
    st.warning(f"The selected series needs at least HS {min_level}-digit data; the active level is {level}-digit.")
    st.stop()
if not prefixes:
    st.info("Choose at least one code.")
    st.stop()
sub = series_base[series_base["hs_code"].str.startswith(prefixes)]
if sub.empty:
    st.warning("No records for this product series under the current filters.")
    st.stop()
included = sorted(sub["hs_code"].unique())
st.caption(
    f"Series: {country_name(rep)} → {country_name(par)} {FLOW_LABELS[flow].lower()}s, {label}. Codes included: {', '.join(included)}. "
    f"Frequency: {'annual' if freq == 'A' else 'monthly'}."
)
series = fcst.build_series(sub, freq)

with st.expander("Model settings", expanded=False):
    e1, e2, e3, e4 = st.columns(4)
    horizon = e1.slider("Forecast horizon", 1, 10 if freq == "A" else 24, 3 if freq == "A" else 12, key="fc_h")
    level_pi = e2.select_slider("Prediction interval", [80, 90, 95], value=int(c.settings.get("forecast_interval_level", 95)), key="fc_pi")
    min_train = e3.number_input(
        "Minimum training size",
        3,
        60,
        int(c.settings.get("forecast_min_train", 5)) if freq == "A" else 24,
        key="fc_mt",
        help="First rolling origin: models are first evaluated after this many observations.",
    )
    tol = e4.number_input(
        "Parsimony tolerance %",
        0.0,
        50.0,
        float(c.settings.get("parsimony_tolerance_pct", 5.0)),
        step=1.0,
        key="fc_tol",
        help="A simpler model is preferred if its error is within this % of the best model.",
    )
cfg = ForecastConfig(
    horizon=horizon,
    min_train=int(min_train),
    interval_level=int(level_pi),
    parsimony_tolerance_pct=float(tol),
    mape_epsilon_share=float(c.settings.get("mape_epsilon_share", 0.01)),
    volatility_threshold=float(c.settings.get("volatility_warning_threshold", 0.5)),
)
res = cached_forecast(tuple(str(i) if freq == "M" else int(i) for i in series.index), tuple(float(v) for v in series.values), freq, cfg.model_dump_json())

for w in res["warnings"]:
    st.warning(w)
if res["status"] in ("insufficient", "failed"):
    st.stop()

st.markdown(f"**Selected model: {res['selected']}** — {res['selection_reason']}")
if res["status"] == "unvalidated":
    st.error("This forecast could not be validated out-of-sample because the series is too short.")
models = list(res["metrics"]["model"]) if not res["metrics"].empty else [res["selected"]]
v1, v2 = st.columns([1, 3])
show_fitted = v1.checkbox("Show in-sample fitted values", value=True, key="fc_fit")
compare = v2.multiselect("Overlay other models' forecasts", [m for m in models if m != res["selected"]], key="fc_cmp")
ui.chart(charts.forecast_chart(res, c.scale, c.unit, freq, show_fitted, compare, cfg.interval_level))
st.caption(
    "Navy: historical observations · grey dotted: in-sample fitted values (selected model) · gold diamonds: one-step-ahead out-of-sample "
    "predictions from rolling-origin backtest · teal dashed: future forecast with shaded prediction interval."
)

left, right = st.columns([3, 2])
with left:
    st.markdown("**Out-of-sample model comparison** (rolling origin, expanding window, one-step-ahead)")
    mt = res["metrics"].copy()
    if not mt.empty:
        mt["selected"] = mt["model"] == res["selected"]
        for col in ("MAE", "RMSE"):
            mt[col] = mt[col] / c.scale
        st.dataframe(
            mt.drop(columns=["complexity"]),
            hide_index=True,
            column_config={
                "MAE": st.column_config.NumberColumn(f"MAE ({c.unit})", format="%.3f"),
                "RMSE": st.column_config.NumberColumn(f"RMSE ({c.unit})", format="%.3f"),
                "MASE": st.column_config.NumberColumn("MASE", format="%.3f", help="Error relative to the in-sample one-step naive error; below 1 beats the naive benchmark."),
                "MAPE": st.column_config.NumberColumn("MAPE %", format="%.1f"),
                "MAPE_excluded": st.column_config.NumberColumn("Near-zero actuals excluded from MAPE"),
                "n_test": "Test points",
                "selected": st.column_config.CheckboxColumn("Selected"),
            },
        )
        st.caption(
            f"Evaluation starts at observation {res['first_test_index'] + 1} of {len(res['used'])}. All models are scored on the same test points; the series is never shuffled."
        )
with right:
    st.markdown(f"**Forecast ({res['selected']}, {cfg.interval_level}% interval)**")
    fc = res["forecasts"]
    sel = fc[fc["model"] == res["selected"]][["period", "forecast", "lower", "upper"]]
    st.dataframe(
        ui.scaled_table(sel, ["forecast", "lower", "upper"], c.scale),
        hide_index=True,
        column_config={
            "forecast": st.column_config.NumberColumn(f"Forecast ({c.unit})", format="%.2f"),
            "lower": st.column_config.NumberColumn("Lower", format="%.2f"),
            "upper": st.column_config.NumberColumn("Upper", format="%.2f"),
        },
    )
    st.download_button("Download forecasts (all models, CSV)", fc.to_csv(index=False).encode("utf-8-sig"), "copper_forecasts.csv", "text/csv", width="stretch")

with st.expander("Backtest predictions, fitted model parameters and diagnostics"):
    bt = res["backtest"].copy()
    st.dataframe(bt, hide_index=True)
    st.json(res.get("model_params", {}))
    for n in res["notes"]:
        st.caption(n)
    st.caption(f"Reproducibility hash of series + settings: `{res['data_hash'][:16]}…`")

st.info(fcst.DISCLAIMER)
st.session_state["forecast_result"] = {"label": f"{country_name(rep)} → {country_name(par)} {FLOW_LABELS[flow].lower()}s, {label}", "result": res, "cfg": cfg}

b1, b2 = st.columns([1, 3])
if b1.button("Save this run to the database", width="stretch"):
    ds_ids = sorted(int(x) for x in sub["dataset_id"].unique())
    run_id = database.save_forecast_run(
        c.engine,
        {
            "series_label": st.session_state["forecast_result"]["label"],
            "frequency": freq,
            "horizon": cfg.horizon,
            "selected_model": res["selected"],
            "data_hash": res["data_hash"],
            "parameters": res["params"] | {"codes": included},
            "metrics": json.loads(res["metrics"].to_json(orient="records")),
            "forecast": json.loads(fc.to_json(orient="records")),
            "warnings": res["warnings"],
            "dataset_ids": ds_ids,
        },
    )
    st.success(f"Saved as forecast run #{run_id}.")
runs = database.list_forecast_runs(c.engine)
if not runs.empty:
    with st.expander(f"Saved forecast runs ({len(runs)})"):
        st.dataframe(runs[["id", "created_at", "series_label", "frequency", "horizon", "selected_model", "data_hash"]], hide_index=True)
        st.caption("Identical data and settings produce the same hash and the same forecasts, so saved runs can be reproduced exactly.")
