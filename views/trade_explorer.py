import numpy as np
import pandas as pd
import streamlit as st

from src import charts, ui
from src import trade_analytics as ta

c = ui.ctx()
ui.page_header("Trade Explorer", "Interactive workspace for bilateral trade trends, rankings, composition and records.", "RQ1")
ui.scope_banner(c)
if not c.has_data:
    ui.empty_state()
    st.stop()
lv = c.level_df
if lv.empty:
    st.warning("No records match the current filters.")
    st.stop()

tabs = st.tabs(["Trends", "Product rankings", "Composition", "Year × product heatmap", "Relationships", "Records"])

with tabs[0]:
    annual = ta.annual_totals(lv)
    ui.chart(charts.trend_lines(annual, c.scale, c.unit, "Annual trade value by series"))
    if c.filters.get("frequency") == "M":
        ui.chart(charts.period_lines(ta.period_series(lv), c.scale, c.unit, "Monthly trade value"))
    rows = []
    for name, grp in annual.groupby("series"):
        g = grp.sort_values("year")
        first, last = g.iloc[0], g.iloc[-1]
        rows.append(
            {
                "series": name,
                "first year": int(first["year"]),
                "last year": int(last["year"]),
                "first value": first["trade_value"] / c.scale,
                "last value": last["trade_value"] / c.scale,
                "CAGR %": ta.cagr(first["trade_value"], last["trade_value"], last["year"] - first["year"]),
                "years observed": int(g["year"].nunique()),
            }
        )
    st.markdown("**Growth summary**")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            "first value": st.column_config.NumberColumn(f"First value ({c.unit})", format="%.2f"),
            "last value": st.column_config.NumberColumn(f"Last value ({c.unit})", format="%.2f"),
            "CAGR %": st.column_config.NumberColumn("CAGR %", format="%.2f", help="Compound annual growth between first and last observed year; blank if either value is zero."),
        },
    )
    yoy = annual.pivot_table(index="year", columns="series", values="yoy_pct")
    st.markdown("**Year-on-year growth (%)** — blank where the previous year is missing or zero")
    st.dataframe(yoy.round(2))
    ui.chart(charts.growth_bars(annual))

if c.level == 0:
    for t in tabs[1:5]:
        with t:
            st.info("Product analysis needs HS product-level data. Select an HS level in the sidebar (only totals are available at the current level).")
else:
    series_df, series_label = ui.series_picker(lv, "te_series", st.sidebar, "Series for product tabs")
    with tabs[1]:
        st.caption(f"Series: {series_label}")
        top_n = st.select_slider("Show top", options=[10, 20, 50], value=10, key="te_top")
        rank = ta.product_ranking(series_df)
        ui.chart(charts.ranking_bar(rank.head(top_n), c.scale, c.unit, f"Top {top_n} products by value"))
        st.dataframe(
            ui.scaled_table(rank.head(top_n), ["trade_value"], c.scale),
            hide_index=True,
            column_config={
                "trade_value": st.column_config.NumberColumn(f"Value ({c.unit})", format="%.3f"),
                "share_pct": st.column_config.ProgressColumn("Share %", format="%.1f", min_value=0, max_value=100),
                "cumulative_share_pct": st.column_config.NumberColumn("Cumulative %", format="%.1f"),
            },
        )
        st.markdown("**Compare products over time**")
        choices = list(rank["hs_code"])
        labels = dict(zip(rank["hs_code"], rank["product"]))
        picked = st.multiselect("Products", choices, default=choices[: min(5, len(choices))], format_func=lambda x: labels[x], key="te_cmp")
        if picked:
            sub = series_df[series_df["hs_code"].isin(picked)].groupby(["year", "hs_code"])["trade_value"].sum().reset_index()
            sub["series"] = sub["hs_code"].map(labels)
            ui.chart(charts.trend_lines(sub, c.scale, c.unit, "Selected products"))
    with tabs[2]:
        st.caption(f"Series: {series_label}")
        cc1, cc2 = st.columns(2)
        grouping = cc1.radio("Group by", ["HS section", "HS chapter", "Product"], horizontal=True, key="te_group")
        mode = cc2.radio("Show", ["Value", "Share of annual total"], horizontal=True, key="te_mode")
        col = {"HS section": "section", "HS chapter": "chapter", "Product": "product"}[grouping]
        d = series_df.copy()
        if col == "product":
            d["product"] = [ta.product_label(h, p) for h, p in zip(d["hs_code"], d["product_description"])]
        if col == "chapter" and c.level < 2:
            st.info("Chapter grouping requires product-level data.")
        else:
            ui.chart(charts.stacked_composition(d, col, c.scale, c.unit, f"Composition by {grouping.lower()}", top_n=8, share=mode != "Value"))
            summ = ta.group_summary(d, col)
            st.dataframe(
                ui.scaled_table(summ, ["trade_value"], c.scale),
                hide_index=True,
                column_config={
                    "trade_value": st.column_config.NumberColumn(f"Value ({c.unit})", format="%.3f"),
                    "share_pct": st.column_config.NumberColumn("Share %", format="%.2f"),
                },
            )
    with tabs[3]:
        st.caption(f"Series: {series_label}")
        n = st.slider("Number of products", 5, 40, 15, key="te_heat_n")
        top_codes = list(ta.product_ranking(series_df, n)["hs_code"])
        m = ta.product_year_matrix(series_df, top_codes)
        if m.empty:
            st.info("No data for heatmap.")
        else:
            m = m.loc[m.sum(axis=1).sort_values(ascending=False).index]
            ui.chart(charts.heatmap(m, c.scale, c.unit, "Trade value by product and year"))
            st.caption("Blank cells mean no record was reported for that product and year (not zero trade).")
    with tabs[4]:
        st.caption(f"Series: {series_label}")
        uv = ta.unit_values(series_df)
        rank_all = ta.product_ranking(series_df)
        ind = rank_all[["hs_code", "classification", "product", "trade_value", "share_pct", "years_present"]].copy()
        growth = []
        vol = []
        for (cl, code), grp in series_df.groupby(["classification", "hs_code"]):
            y = grp.groupby("year")["trade_value"].sum().sort_index()
            growth.append(
                {
                    "classification": cl,
                    "hs_code": code,
                    "cagr_pct": ta.cagr(y.iloc[0], y.iloc[-1], y.index[-1] - y.index[0]) if len(y) > 1 else np.nan,
                    "volatility": float(np.nanstd(ta.yoy_growth(y).values)) if len(y) > 2 else np.nan,
                }
            )
        ind = ind.merge(pd.DataFrame(growth), on=["classification", "hs_code"], how="left")
        if not uv.empty:
            ind = ind.merge(uv[["classification", "hs_code", "net_weight_kg", "usd_per_kg"]], on=["classification", "hs_code"], how="left")
        options = {
            "trade_value": "Total value (USD)",
            "share_pct": "Share of series (%)",
            "cagr_pct": "CAGR (%)",
            "volatility": "Volatility of YoY growth (pp)",
            "years_present": "Years with records",
        }
        if "net_weight_kg" in ind:
            options.update({"net_weight_kg": "Net weight (kg)", "usd_per_kg": "Unit value (USD/kg)"})
        s1, s2, s3 = st.columns(3)
        xk = s1.selectbox("X axis", list(options), index=list(options).index("net_weight_kg") if "net_weight_kg" in options else 0, format_func=options.get, key="te_x")
        yk = s2.selectbox("Y axis", list(options), index=0 if "net_weight_kg" in options else 2, format_func=options.get, key="te_y")
        log = s3.checkbox("Log scales", value=True, key="te_log", help="Log scales drop zero and negative values.")
        ui.chart(charts.scatter(ind, xk, yk, "product", f"{options[yk]} vs {options[xk]}", options[xk], options[yk], log=log, size="trade_value"))
        st.caption("Each point is a product. Bubble size reflects total value. Unit values use only records that report net weight.")

with tabs[5]:
    st.caption("All records under the current filters (all product levels shown at the selected level only).")
    q = st.text_input("Search records (code, description, country)", key="te_search")
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
        "quality_flags",
    ]
    rec = lv[cols].copy()
    if q:
        mask = rec.astype(str).apply(lambda col: col.str.contains(q, case=False, regex=False)).any(axis=1)
        rec = rec[mask]
    st.dataframe(
        rec.sort_values(["period", "trade_value"], ascending=[True, False]),
        hide_index=True,
        height=420,
        column_config={"trade_value": st.column_config.NumberColumn("Trade value (USD)", format="%.0f")},
    )
    st.caption(f"{len(rec):,} records")
    ui.download_buttons(rec, "filtered_trade_records", "te_dl", "records")
