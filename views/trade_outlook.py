import json

import pandas as pd
import streamlit as st

from src import charts, ui
from src import outlook as ol
from src import trade_analytics as ta
from src.reporting import to_excel_bytes

c = ui.ctx()
ui.page_header("Trade Outlook (5 and 10 years)", "Where Zambia–China trade could be in five and ten years: statistical projections, copper production scenarios and the signals to watch.", "RQ3")
ui.scope_banner(c, "Uses annual records and the sidebar year range. Reporter, partner, flow and product filters are set by the outlook itself.")
if not c.has_data:
    ui.empty_state()
    st.stop()

annual = c.all_data[(c.all_data["frequency"] == "A") & (c.all_data["currency"] == c.filters.get("currency", "USD"))]
if annual.empty:
    st.warning("The outlook needs annual records. Import annual UN Comtrade data on the Data Management page.")
    st.stop()
y0, y1 = c.filters.get("years", (int(annual["year"].min()), int(annual["year"].max())))
annual = annual[(annual["year"] >= y0) & (annual["year"] <= y1)]
if c.filters.get("frequency") == "M":
    st.caption("The sidebar is set to monthly data; the outlook always uses the annual series for the same years.")


@st.cache_data(show_spinner="Projecting the main series…", max_entries=16)
def cached_projection(payload: str, horizon: int, interval: int, min_train: int, tol: float) -> dict:
    raw = json.loads(payload)
    series = {k: pd.Series(v["values"], index=v["index"], dtype=float) for k, v in raw.items()}
    return ol.project(series, horizon, interval, min_train, tol)


series = ol.build_series(annual)
if "copper" not in series and "exports" not in series:
    st.warning("Neither Zambia-reported copper exports nor total exports to China are loaded. Import the Zambia → China export dataset first.")
    st.stop()
last_year = max(int(s.index.max()) for s in series.values())

with st.expander("Outlook settings", expanded=False):
    e1, e2, e3, e4 = st.columns(4)
    horizon = e1.slider("Years ahead", 5, 10, 10, key="ol_h", help="Five years gives the medium-term milestone; ten years the long-term one.")
    interval = e2.select_slider("Prediction interval", [80, 90, 95], value=int(c.settings.get("forecast_interval_level", 95)), key="ol_pi")
    min_train = e3.number_input("Minimum training size", 3, 30, int(c.settings.get("forecast_min_train", 5)), key="ol_mt")
    tol = e4.number_input("Parsimony tolerance %", 0.0, 50.0, float(c.settings.get("parsimony_tolerance_pct", 5.0)), step=1.0, key="ol_tol")

payload = json.dumps({k: {"index": [int(i) for i in s.index], "values": [float(v) for v in s.values]} for k, s in series.items()})
results = cached_projection(payload, int(horizon), int(interval), int(min_train), float(tol))
marks = ol.milestones(last_year, int(horizon))
table = ol.projection_table(results, marks)
paths = ol.balance_paths(results)

k = st.columns(len(marks) + 2)
lead = "copper" if not table.empty and "copper" in set(table["key"]) else ("exports" if not table.empty and "exports" in set(table["key"]) else None)
if lead:
    row = table.set_index("key").loc[lead]
    name = "Copper exports to China" if lead == "copper" else "Exports to China"
    for i, y in enumerate(marks):
        if f"{y}" in row and pd.notna(row[f"{y}"]):
            ui.kpi(k[i], f"{name}, {y}", c.short(row[f"{y}"]), help=f"{row['model']} model, {interval}% interval {c.short(row[f'{y} lower'])}–{c.short(row[f'{y} upper'])}.")
if not paths.empty:
    sel_paths = paths[paths["basis"] == "Selected models"].set_index("year")["balance"]
    ui.kpi(k[-2], f"Balance with China, {marks[-1]}", c.short(sel_paths.get(marks[-1], float("nan"))), help="Projected exports minus projected imports, selected models.")
    flip = sel_paths[sel_paths < 0]
    first = int(flip.index.min()) if not flip.empty else None
    ui.kpi(k[-1], "First projected deficit year", str(first) if first else "Not within horizon",
           help=f"First year the projected balance (selected models) falls below zero; in {first} it is {c.short(sel_paths[first])}." if first else "The projected balance stays positive to the end of the horizon.")

tab1, tab2, tab3 = st.tabs(["Statistical projections", "Copper production scenarios", "Signals to monitor"])

with tab1:
    st.markdown(f"Each series is fitted with the same four annual models as the forecasting page and carried forward to **{last_year + int(horizon)}**. "
                "The model with the best out-of-sample backtest is selected; the range across all four models shows how much the answer depends on that choice.")
    show = table.copy()
    cols = {"series": "Series", "model": "Selected model", "mase": "Backtest MASE"}
    for y in marks:
        cols.update({f"{y}": f"{y}", f"{y} lower": f"{y} lower", f"{y} upper": f"{y} upper", f"{y} min of models": f"{y} min (4 models)", f"{y} max of models": f"{y} max (4 models)"})
    num = [col for col in show.columns if col[:4].isdigit()]
    show = ui.scaled_table(show, num, c.scale)
    st.dataframe(show[list(cols)].rename(columns=cols), hide_index=True,
                 column_config={v: st.column_config.NumberColumn(f"{v} ({c.unit})", format="%.1f") for kk, v in cols.items() if kk[:4].isdigit()} | {"Backtest MASE": st.column_config.NumberColumn(format="%.3f")})
    pick = st.selectbox("Series to chart", list(results), format_func=lambda x: ol.SERIES[x][0], key="ol_series")
    ui.chart(charts.outlook_chart(series[pick], results[pick], None, c.scale, c.unit, int(interval), f"{ol.SERIES[pick][0]}: history and projections"))
    if not paths.empty:
        hist_bal = None
        if "exports" in series and "imports" in series:
            hist_bal = (series["exports"] - series["imports"]).dropna()
        if hist_bal is not None and not hist_bal.empty:
            ui.chart(charts.balance_chart(hist_bal, paths, c.scale, c.unit))
            st.caption("The two projected lines differ only in the models used. Whether the surplus survives depends on whether copper exports grow; the history of imports gives no reason to expect import growth to stop.")
    res_notes = [w for r in results.values() for w in r.get("warnings", [])]
    for w in dict.fromkeys(res_notes):
        st.warning(w)

with tab2:
    st.markdown("Copper exports to China are modelled as **production × share sent to China × price per tonne**. "
                "The share and price come from your data for the base year; national production comes from published figures you can change.")
    ref = ol.PRODUCTION_REFERENCE
    p1, p2, p3, p4 = st.columns(4)
    base_years = sorted(int(y) for y in annual["year"].unique())
    base_year = p1.selectbox("Base year", base_years, index=base_years.index(ref["base_year"]) if ref["base_year"] in base_years else len(base_years) - 1, key="ol_by")
    nat = p2.number_input("National copper production in base year (t)", 1.0, 10_000_000.0, float(ref["base_production_t"]), step=1000.0, key="ol_nat",
                          help=f"Default: {ref['base_source']}. Change it if you use a different source or base year.")
    start_t = p3.number_input(f"Production in {ref['start_year']} (t), starting point", 1.0, 10_000_000.0, float(ref["start_production_t"]), step=1000.0, key="ol_start", help=f"Default: {ref['start_source']}.")
    band = p4.slider("Price band ± %", 0, 60, 25, step=5, key="ol_band", help="Copper prices move a lot; the band shows the effect of a higher or lower price per tonne.")
    inputs = ol.base_inputs(annual, int(base_year), float(nat))
    if inputs is None:
        st.warning("Copper-related exports to China with net weights are needed for the base year (HS 4- or 6-digit data).")
    else:
        b1, b2, b3, b4 = st.columns(4)
        ui.kpi(b1, f"Copper exports to China, {base_year}", c.short(inputs.value))
        ui.kpi(b2, "Tonnes sent to China", f"{inputs.tonnes:,.0f} t", help=f"Net weight covers {inputs.value_coverage_pct:.0f}% of the value; the rest is estimated at the same price per tonne.")
        ui.kpi(b3, "Share of national production", ui.pct(inputs.share * 100, signed=False))
        ui.kpi(b4, "Average price per tonne", f"US${inputs.unit_value:,.0f}")
        if inputs.share > 1:
            st.error("The tonnes sent to China exceed the national production entered. Check the base-year production figure.")
        st.markdown("**Scenarios** — edit, add or remove rows. Production rises in a straight line from the starting point to the target and then stays there.")
        sc_df = st.data_editor(pd.DataFrame(ol.DEFAULT_SCENARIOS), num_rows="dynamic", hide_index=True, key="ol_sc", width="stretch",
                               column_config={"scenario": st.column_config.TextColumn("Scenario", required=True),
                                              "target_t": st.column_config.NumberColumn("Target production (t)", min_value=1.0, format="%.0f", required=True),
                                              "target_year": st.column_config.NumberColumn("Target year", min_value=ref["start_year"], max_value=ref["start_year"] + 20, step=1, format="%d", required=True)})
        scenarios = [r for r in sc_df.dropna().to_dict("records") if r.get("scenario")][:5]
        end_year = last_year + int(horizon)
        frame = ol.scenario_frame(scenarios, inputs, ref["start_year"], float(start_t), end_year, float(band)) if scenarios else pd.DataFrame()
        if not frame.empty:
            ui.chart(charts.outlook_chart(series["copper"], results.get("copper"), frame, c.scale, c.unit, int(interval), "Copper-related exports to China: statistical projection and production scenarios", show_models=False)
                     if "copper" in series else charts.outlook_chart(series["exports"], None, frame, c.scale, c.unit, int(interval), "Production scenarios"))
            summary = []
            for s in scenarios:
                g = frame[frame["scenario"] == s["scenario"]].set_index("year")
                row = {"Scenario": s["scenario"], "Growth needed per year": ol.required_growth(float(start_t), ref["start_year"], float(s["target_t"]), int(s["target_year"]))}
                for y in marks:
                    if y in g.index:
                        row[f"Production {y} (t)"] = g.loc[y, "production_t"]
                        row[f"Value {y}"] = g.loc[y, "value"] / c.scale
                        row[f"Range {y}"] = f"{g.loc[y, 'low'] / c.scale:,.1f}–{g.loc[y, 'high'] / c.scale:,.1f}"
                summary.append(row)
            st.dataframe(pd.DataFrame(summary), hide_index=True,
                         column_config={"Growth needed per year": st.column_config.NumberColumn(format="%.1f%%")}
                         | {f"Value {y}": st.column_config.NumberColumn(f"Value {y} ({c.unit})", format="%.1f") for y in marks}
                         | {f"Production {y} (t)": st.column_config.NumberColumn(format="%,.0f") for y in marks})
            st.caption("‘Growth needed per year’ is the compound growth in national production from the starting point to the target. "
                       "Compare it with recent growth: a target far above what has been achieved signals a demanding scenario.")
            st.session_state["outlook_scenarios"] = frame

with tab3:
    st.markdown("These indicators can be updated every year from new UN Comtrade releases. Comparing each new year with the scenarios shows which path trade is following.")
    lv = ol.best_level(annual)
    zx = annual[(annual["reporter_code"] == ol.ZAMBIA) & (annual["partner_code"] == ol.CHINA) & (annual["flow"] == "X")]
    rows = []
    yrs = sorted(int(y) for y in zx["year"].unique())
    for y in yrs[-3:]:
        r = {"Year": y}
        tot = zx[(zx["year"] == y) & (zx["hs_level"] == 0)]["trade_value"].sum()
        if "copper" in series and y in series["copper"].index:
            r["Copper-related exports"] = float(series["copper"].loc[y]) / c.scale
            r["Copper share of exports %"] = float(series["copper"].loc[y]) / tot * 100 if tot else float("nan")
        if lv:
            prod = zx[(zx["year"] == y) & (zx["hs_level"] == lv)]
            conc = ta.concentration_by_year(prod)
            r["HHI (export concentration)"] = float(conc["hhi_points"].iloc[0]) if not conc.empty else float("nan")
        if "exports" in series and "imports" in series and y in series["imports"].index:
            r["Trade balance"] = (float(series["exports"].loc[y]) - float(series["imports"].loc[y])) / c.scale
        if "china_imports" in series and y in series["china_imports"].index and tot:
            r["Mirror ratio (China ÷ Zambia)"] = float(series["china_imports"].loc[y]) / tot
        rows.append(r)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     column_config={"Year": st.column_config.NumberColumn(format="%d"),
                                    "Copper-related exports": st.column_config.NumberColumn(f"Copper-related exports ({c.unit})", format="%.1f"),
                                    "Copper share of exports %": st.column_config.NumberColumn(format="%.1f"),
                                    "HHI (export concentration)": st.column_config.NumberColumn(format="%.0f"),
                                    "Trade balance": st.column_config.NumberColumn(f"Trade balance ({c.unit})", format="%.1f"),
                                    "Mirror ratio (China ÷ Zambia)": st.column_config.NumberColumn(format="%.2f")})
    frame = st.session_state.get("outlook_scenarios")
    if frame is not None and "copper" in series:
        near = ol.nearest_scenario(frame, series["copper"])
        if near.empty:
            st.info(f"No observed year after the scenario start ({ol.PRODUCTION_REFERENCE['start_year']}) is loaded yet. When newer data are imported, this panel will show which scenario the observed values are closest to.")
        else:
            st.markdown(f"**Closest scenario so far:** {near.iloc[0]['scenario']} (compared over {int(near.iloc[0]['years_compared'])} year(s)).")
            st.dataframe(ui.scaled_table(near, ["mean_abs_gap"], c.scale), hide_index=True,
                         column_config={"mean_abs_gap": st.column_config.NumberColumn(f"Average gap ({c.unit})", format="%.1f")})
    st.markdown(
        "- **Copper production and power supply** decide which scenario is realistic.\n"
        "- **Copper price** moves the value up or down within each scenario's band.\n"
        "- **Transport corridors** (TAZARA, Lobito) affect where copper is sold and therefore how it is recorded.\n"
        "- **Non-copper exports** under China's zero-tariff treatment are the only route to lower concentration (HHI).\n"
        "- **Mirror ratio** shows whether recording of trade through third countries is changing."
    )

st.divider()
export = {"Projections": table, "Balance": paths}
if isinstance(st.session_state.get("outlook_scenarios"), pd.DataFrame):
    export["Scenarios"] = st.session_state["outlook_scenarios"]
d1, d2, _ = st.columns([1, 1, 3])
d1.download_button("Download outlook (Excel)", to_excel_bytes({k: v for k, v in export.items() if not v.empty}), "trade_outlook.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
d2.download_button("Download projections (CSV)", table.to_csv(index=False).encode("utf-8-sig"), "trade_outlook_projections.csv", "text/csv", width="stretch")
st.info(ol.DISCLAIMER)
