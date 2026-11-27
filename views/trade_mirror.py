import streamlit as st

from src import charts, ui
from src import mirror_analysis as mi
from src import trade_analytics as ta
from src.reporting import to_excel_bytes
from src.schema import country_name

c = ui.ctx()
ui.page_header("Trade Mirror Analysis", "Zambia-reported exports to China compared with China-reported imports from Zambia.", "RQ2")
ui.scope_banner(
    c, "This page applies the sidebar year, level and product filters. Reporter, partner and flow are set below because a mirror comparison always needs both reporters."
)
if not c.has_data:
    ui.empty_state()
    st.stop()

base = c.apply(c.scope, skip=("reporters", "partners", "flows"))
countries = sorted(set(base["reporter_code"]) | set(base["partner_code"]), key=country_name)
s1, s2, s3 = st.columns([1, 1, 2])
a = s1.selectbox("Reporter A", countries, index=countries.index("894") if "894" in countries else 0, format_func=country_name, key="mi_a")
b_opts = [x for x in countries if x != a] or countries
b = s2.selectbox("Partner B", b_opts, index=b_opts.index("156") if "156" in b_opts else 0, format_func=country_name, key="mi_b")
direction = s3.radio("Comparison", list(mi.DIRECTIONS), horizontal=True, key="mi_dir", format_func=lambda d: mi.DIRECTIONS[d][2].format(a=country_name(a), b=country_name(b)))
level = c.level if c.level is not None else 0
res = mi.mirror_compare(base, a, b, level, direction)
st.session_state["mirror_result"] = res

if res["status"] != "ok":
    st.info(res["message"])
    have = base.groupby(["reporter_code", "partner_code", "flow"]).size().reset_index(name="records")
    have["reporter"] = have["reporter_code"].map(country_name)
    have["partner"] = have["partner_code"].map(country_name)
    st.markdown("**Reporter perspectives currently loaded (after filters)**")
    st.dataframe(have[["reporter", "partner", "flow", "records"]], hide_index=True)
    st.page_link("views/data_management.py", label="Go to Data Management to import the partner's dataset", icon="🗄️")
else:
    sm = res["summary"]
    st.markdown(f"#### {res['title']} · {ta.level_label(level)}")
    if res.get("message"):
        st.caption(res["message"])
    k = st.columns(5)
    ui.kpi(
        k[0],
        "Match rate",
        ui.pct(sm["match_rate_pct"], signed=False),
        delta=f"{sm['records_matched']} of {sm['records_total']} records",
        delta_color="off",
        help="Share of year–product keys reported by both sides.",
    )
    ui.kpi(k[1], "Value coverage", ui.pct(sm["value_coverage_pct"], signed=False), help=f"Share of {res['a_label']} value that has a matching partner record.")
    ui.kpi(k[2], "Aggregate discrepancy", ui.pct(sm["aggregate_pct_discrepancy"]), help=f"(Σ{res['b_label']} − Σ{res['a_label']}) / Σ{res['a_label']} over matched records.")
    ui.kpi(k[3], "Median record discrepancy", ui.pct(sm["median_pct_discrepancy"]))
    ui.kpi(
        k[4], "Records within ±10%", ui.pct(sm["share_within_10pct"], signed=False), delta=f"{sm['undefined_pct']} undefined %" if sm["undefined_pct"] else None, delta_color="off"
    )
    ui.chart(charts.mirror_bars(res["annual"], res["a_label"], res["b_label"], c.scale, c.unit))
    left, right = st.columns([1, 1])
    with left:
        ui.chart(charts.mirror_scatter(res["records"], res["a_label"], res["b_label"], c.scale, c.unit))
    with right:
        st.markdown("**Annual discrepancy (matched records)**")
        st.dataframe(
            ui.scaled_table(res["annual"], ["value_a", "value_b", "abs_discrepancy"], c.scale),
            hide_index=True,
            column_config={
                "value_a": st.column_config.NumberColumn(f"{res['a_label']} ({c.unit})", format="%.2f"),
                "value_b": st.column_config.NumberColumn(f"{res['b_label']} ({c.unit})", format="%.2f"),
                "abs_discrepancy": st.column_config.NumberColumn(f"B − A ({c.unit})", format="%.2f"),
                "pct_discrepancy": st.column_config.NumberColumn("Discrepancy %", format="%.1f"),
                "mirror_ratio": st.column_config.NumberColumn("Ratio B/A", format="%.3f"),
            },
        )
    if level > 0:
        st.markdown("**Largest discrepancies by product** (sorted by absolute difference over matched years)")
        st.dataframe(
            ui.scaled_table(res["by_product"].head(25), ["value_a", "value_b", "abs_discrepancy"], c.scale),
            hide_index=True,
            column_config={
                "value_a": st.column_config.NumberColumn(f"{res['a_label']} ({c.unit})", format="%.3f"),
                "value_b": st.column_config.NumberColumn(f"{res['b_label']} ({c.unit})", format="%.3f"),
                "abs_discrepancy": st.column_config.NumberColumn(f"B − A ({c.unit})", format="%.3f"),
                "pct_discrepancy": st.column_config.NumberColumn("Discrepancy %", format="%.1f"),
            },
        )
    st.markdown("**Record-level comparison**")
    statuses = sorted(res["records"]["match_status"].unique())
    pick = st.multiselect("Match status", statuses, default=statuses, key="mi_status")
    recs = res["records"][res["records"]["match_status"].isin(pick)]
    st.dataframe(
        recs.drop(columns=["year"]),
        hide_index=True,
        height=360,
        column_config={
            "value_a": st.column_config.NumberColumn(f"{res['a_label']} (USD)", format="%.0f"),
            "value_b": st.column_config.NumberColumn(f"{res['b_label']} (USD)", format="%.0f"),
            "abs_discrepancy": st.column_config.NumberColumn("B − A (USD)", format="%.0f"),
            "pct_discrepancy": st.column_config.NumberColumn("Discrepancy %", format="%.1f"),
            "mirror_ratio": st.column_config.NumberColumn("Ratio B/A", format="%.3f"),
        },
    )
    st.caption(
        f"Unmatched: {sm['a_only']} records reported only by {country_name(a)}, {sm['b_only']} only by {country_name(b)}, "
        f"{sm['incomparable']} incomparable because the HS version differs. Unmatched records have no discrepancy value; the missing side is never assumed to be zero."
    )
    d1, d2, _ = st.columns([1, 1, 3])
    d1.download_button("Download records (CSV)", res["records"].to_csv(index=False).encode("utf-8-sig"), "mirror_records.csv", "text/csv", width="stretch")
    d2.download_button(
        "Download all tables (Excel)",
        to_excel_bytes(
            {"records": res["records"], "annual": res["annual"], "by_product": res["by_product"]},
            {"comparison": res["title"], "level": ta.level_label(level), **ui.describe_filters(c)},
        ),
        "mirror_analysis.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )

with st.expander("Methodology: formulas and why mirror statistics differ", expanded=res["status"] != "ok"):
    st.markdown(
        "**Matching key:** year (and month for monthly data) + HS classification version + commodity code, at one HS level. Only records present on both sides are 'matched'."
    )
    st.markdown(
        "<div class='formula'>Absolute discrepancy = B-reported value − A-reported value<br>"
        "Percentage discrepancy = (B − A) / A × 100   (undefined when A = 0)<br>"
        "Mirror ratio = B / A   (undefined when A = 0)<br>"
        "Match rate = matched keys / all keys reported by either side</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "With A = Zambia (exports, FOB) and B = China (imports, CIF), a positive discrepancy of a few percent is expected from freight and "
        "insurance costs alone. **A discrepancy is not evidence of fraud or inaccurate reporting.** Common legitimate causes:"
    )
    for title, text in mi.CAUSES:
        st.markdown(f"- **{title}.** {text}")
