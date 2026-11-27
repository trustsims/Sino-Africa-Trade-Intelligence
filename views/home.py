import pandas as pd
import streamlit as st

from src import charts, ui
from src import trade_analytics as ta
from src.schema import country_name

c = ui.ctx()
ui.page_header("Executive Overview", "Headline indicators for bilateral trade under the current filters.", "RQ1 · RQ3")
ui.scope_banner(c)
if not c.has_data:
    ui.empty_state()
    st.stop()

lv = ta.at_level(c.apply(c.scope, skip=("flows",)), c.level)
if lv.empty:
    st.warning("No records match the current filters. Widen the year range or clear product filters in the sidebar.")
    st.stop()

reporters = sorted(lv["reporter_code"].unique(), key=country_name)
col_a, col_b, _ = st.columns([1, 1, 2])
rep = col_a.selectbox(
    "Focus reporter",
    reporters,
    index=reporters.index("894") if "894" in reporters else 0,
    format_func=country_name,
    help="Reporting country whose statistics drive the KPIs below.",
)
partners = sorted(lv.loc[lv["reporter_code"] == rep, "partner_code"].unique(), key=country_name)
par = col_b.selectbox("Focus partner", partners, index=partners.index("156") if "156" in partners else 0, format_func=country_name)
pair = lv[(lv["reporter_code"] == rep) & (lv["partner_code"] == par)]
rname, pname = country_name(rep), country_name(par)
exports = pair[pair["flow"] == "X"]
imports = pair[pair["flow"] == "M"]

ex_year = exports.groupby("year")["trade_value"].sum().sort_index()
im_year = imports.groupby("year")["trade_value"].sum().sort_index()
growth = ta.yoy_growth(ex_year) if len(ex_year) else pd.Series(dtype=float)
last_growth = growth.iloc[-1] if len(growth) else float("nan")
cop = ta.copper_breakdown(exports) if not exports.empty else {"available": False, "note": "No export records under the current filters."}

active = c.datasets[(c.datasets["is_active"]) & (c.datasets["status"] == "complete")] if not c.datasets.empty else c.datasets
n_warn = 0
n_excl = 0
for summ in active.get("cleaning_summary", []):
    if isinstance(summ, dict):
        n_warn += sum(1 for ch in summ.get("dataset_checks", []) if ch.get("severity") == "warning")
        n_excl += int(summ.get("excluded_rows", 0))

r1 = st.columns(4)
ui.kpi(
    r1[0],
    f"Exports {rname} → {pname}",
    c.short(ex_year.sum()) if len(ex_year) else "n/a",
    help=f"Sum of {rname}-reported exports to {pname}, {ui.period_label(c.filters)}, at {ta.level_label(c.level)}.",
)
ui.kpi(
    r1[1],
    f"Imports {rname} ← {pname}",
    c.short(im_year.sum()) if len(im_year) else "not available",
    help="Imports reported by the focus reporter from the focus partner. This page always shows both flows, whatever the Trade flow filter says.",
)
common = ex_year.index.intersection(im_year.index)
bal = (ex_year.loc[common] - im_year.loc[common]).sum() if len(common) else None
ui.kpi(r1[2], "Trade balance", c.short(bal) if bal is not None else "not available", help="Exports minus imports over years where both flows are reported by the focus reporter.")
ui.kpi(
    r1[3],
    f"Export growth {int(ex_year.index[-1]) if len(ex_year) else ''}",
    ui.pct(last_growth),
    help="Year-on-year change in exports versus the previous calendar year; n/a if the previous year is missing or zero.",
)

r2 = st.columns(4)
if cop.get("available") and cop.get("ore_available"):
    t = cop["table"]
    ui.kpi(r2[0], "Copper ore exports (HS 2603)", c.short(t["copper_ore_2603"].sum()), help="Copper ores and concentrates (HS 2603 / 260300) over the selected period.")
    ui.kpi(r2[1], "Copper ore share", ui.pct(t["copper_ore_2603"].sum() / t["total"].sum() * 100, signed=False))
elif cop.get("available"):
    t = cop["table"]
    ui.kpi(r2[0], "Copper ore exports (HS 2603)", "not separable", help=cop.get("note"))
    ui.kpi(r2[1], "Copper-related share", ui.pct(t["copper_related"].sum() / t["total"].sum() * 100, signed=False), help=cop.get("note"))
else:
    ui.kpi(r2[0], "Copper ore exports (HS 2603)", "n/a", help=cop.get("note"))
    ui.kpi(r2[1], "Copper ore share", "n/a", help=cop.get("note"))
n_products = exports.groupby(["classification", "hs_code"]).ngroups if c.level and c.level > 0 else 0
ui.kpi(
    r2[2],
    "Products exported",
    f"{n_products:,}" if c.level else "n/a",
    help=f"Distinct commodity codes with export records at {ta.level_label(c.level)}. See Product Composition for genuine diversification measures.",
)
yrs = sorted(pair["year"].unique())
ui.kpi(
    r2[3],
    "Coverage",
    f"{yrs[0]}–{yrs[-1]}" if yrs else "n/a",
    delta=f"{len(c.filtered):,} records · {n_warn} warnings",
    delta_color="off",
    help=f"{n_excl:,} source rows were excluded during validation across active datasets (see Data Management).",
)

if c.filters.get("frequency") == "M":
    chosen = c.filters.get("months") or []
    if chosen:
        st.caption(f"Yearly values sum only the selected months ({', '.join(ui.MONTHS[m - 1] for m in sorted(chosen))}) of each year.")
    else:
        months = pair.groupby("year")["month"].nunique()
        partial = [int(y) for y, n in months.items() if n < 12]
        if partial:
            st.caption(f"Yearly values are sums of monthly records; these years have fewer than 12 months in the selected period or data: {', '.join(map(str, partial))}.")

annual = ta.annual_totals(pair)
left, right = st.columns([3, 2])
with left:
    if not annual.empty:
        ui.chart(charts.trend_lines(annual, c.scale, c.unit, f"Annual trade: {rname} and {pname}"))
with right:
    if not annual.empty and annual["yoy_pct"].notna().any():
        ui.chart(charts.growth_bars(annual))
    else:
        st.info("Growth rates need at least two consecutive years.")

if c.level and c.level > 0 and not exports.empty:
    left, right = st.columns([1, 1])
    with left:
        rank = ta.product_ranking(exports, int(c.settings.get("top_n", 10)))
        ui.chart(charts.ranking_bar(rank, c.scale, c.unit, f"Top exported products ({ui.period_label(c.filters)})"))
    with right:
        ui.chart(charts.stacked_composition(exports, "section", c.scale, c.unit, "Export composition by HS section (% of annual total)", share=True))

if cop.get("available"):
    t = cop["table"]
    import plotly.graph_objects as go

    fig = go.Figure()
    if cop.get("ore_available"):
        fig.add_trace(go.Bar(x=t["year"], y=t["copper_ore_2603"] / c.scale, name="Copper ores & concentrates (HS 2603)", marker_color=charts.NAVY))
    fig.add_trace(
        go.Scatter(x=t["year"], y=t["copper_related"] / c.scale, name="All copper-related (HS 2603 + Ch. 74)", mode="lines+markers", line=dict(color=charts.TEAL, width=2.5))
    )
    fig.update_layout(title=f"Copper exports: {rname} → {pname}", yaxis_title=c.unit, xaxis=dict(dtick=1, tickformat="d"), height=360)
    ui.chart(fig)
    if cop.get("note"):
        st.caption(cop["note"])

st.subheader("Observed changes")
notes = ta.observations(pair, c.unit, c.scale)
if notes:
    st.markdown("<div class='obs'><ul>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul></div>", unsafe_allow_html=True)
    st.caption("Descriptive statements calculated from the active dataset. They describe what changed, not why it changed.")
else:
    st.info("Not enough data under the current filters to describe changes.")

no_product_filter = not (c.filters.get("sections") or c.filters.get("chapters") or c.filters.get("products"))
rec = ta.reconciliation(c.apply(c.scope), c.level) if no_product_filter else pd.DataFrame()
if not rec.empty:
    with st.expander("Coverage check: product-level sum vs. reported TOTAL"):
        st.dataframe(
            ui.scaled_table(rec, ["product_level_sum", "reported_total"], c.scale),
            hide_index=True,
            column_config={
                "product_level_sum": st.column_config.NumberColumn(f"Product-level sum ({c.unit})", format="%.2f"),
                "reported_total": st.column_config.NumberColumn(f"Reported TOTAL ({c.unit})", format="%.2f"),
                "coverage_pct": st.column_config.NumberColumn("Coverage %", format="%.1f"),
            },
        )
        st.caption("Differences arise when some product lines are confidential, suppressed or below the reporting threshold.")
