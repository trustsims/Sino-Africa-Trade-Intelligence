import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import charts, database, ui
from src import trade_analytics as ta
from src.data_ingestion import IngestionError, read_table
from src.schema import CLASSIFICATION_LABELS

c = ui.ctx()
ui.page_header("Product Composition & Concentration", "What dominates the trade basket, and how concentrated is it?", "RQ1")
ui.scope_banner(c)
if not c.has_data:
    ui.empty_state()
    st.stop()
if c.level_df.empty:
    st.warning("No records match the current filters.")
    st.stop()
if c.level == 0:
    st.info("Only all-commodity totals are available at the selected level. Choose an HS product level in the sidebar.")
    st.stop()

df, label = ui.series_picker(c.level_df, "pc_series")
st.caption(f"Series: {label} · {ta.level_label(c.level)}")

tab_top, tab_trend, tab_hs, tab_cu, tab_conc, tab_map = st.tabs(
    ["Top products", "Product trends", "Chapters & headings", "Copper", "Concentration & diversification", "Classification mapping"]
)

with tab_top:
    rank = ta.product_ranking(df)
    sub = st.tabs(["Top 10", "Top 20", "Top 50"])
    for t, n in zip(sub, (10, 20, 50)):
        with t:
            r = rank.head(n)
            if n == 10:
                ui.chart(charts.ranking_bar(r, c.scale, c.unit, "Top 10 products"))
            st.dataframe(
                ui.scaled_table(r, ["trade_value"], c.scale),
                hide_index=True,
                column_config={
                    "trade_value": st.column_config.NumberColumn(f"Value ({c.unit})", format="%.3f"),
                    "share_pct": st.column_config.ProgressColumn("Share %", format="%.1f", min_value=0, max_value=100),
                    "cumulative_share_pct": st.column_config.NumberColumn("Cumulative %", format="%.1f"),
                },
            )
            if len(rank) < n:
                st.caption(f"Only {len(rank)} products are present in this series.")
    ui.download_buttons(rank, "product_ranking", "pc_rank")

with tab_trend:
    rank = ta.product_ranking(df)
    labels = dict(zip(rank["hs_code"], rank["product"]))
    code = st.selectbox("Product", list(rank["hs_code"]), format_func=lambda x: labels[x], key="pc_prod")
    p = df[df["hs_code"] == code]
    y = p.groupby("year")["trade_value"].sum().sort_index()
    tot = df.groupby("year")["trade_value"].sum()
    share = y / tot.reindex(y.index) * 100
    fig = go.Figure()
    fig.add_trace(go.Bar(x=y.index, y=y.values / c.scale, name="Value", marker_color=charts.NAVY))
    fig.add_trace(go.Scatter(x=share.index, y=share.values, name="Share of series %", yaxis="y2", mode="lines+markers", line=dict(color=charts.TEAL)))
    fig.update_layout(
        title=labels[code],
        yaxis_title=c.unit,
        yaxis2=dict(title="Share %", overlaying="y", side="right", showgrid=False, rangemode="tozero"),
        xaxis=dict(dtick=1, tickformat="d"),
        height=400,
    )
    ui.chart(fig)
    g = ta.yoy_growth(y)
    w = p.groupby("year")["net_weight_kg"].sum(min_count=1)
    tbl = pd.DataFrame({"year": y.index, f"value ({c.unit})": y.values / c.scale, "YoY %": g.values, "share %": share.values, "net weight (t)": (w.reindex(y.index) / 1000).values})
    tbl["USD per kg"] = y.values / w.reindex(y.index).values
    st.dataframe(tbl, hide_index=True, column_config={c_: st.column_config.NumberColumn(format="%.2f") for c_ in tbl.columns if c_ != "year"})

with tab_hs:
    d = df.copy()
    if c.level >= 4:
        d["heading"] = d["hs_code"].str[:4]
    ch = ta.group_summary(d, "chapter")
    st.markdown("**HS chapter summary** (2-digit totals built from the selected level)")
    st.dataframe(
        ui.scaled_table(ch, ["trade_value"], c.scale),
        hide_index=True,
        column_config={
            "trade_value": st.column_config.NumberColumn(f"Value ({c.unit})", format="%.3f"),
            "share_pct": st.column_config.NumberColumn("Share %", format="%.2f"),
            "products": "Codes",
        },
    )
    if c.level >= 4:
        hd = ta.group_summary(d, "heading")
        desc = d.dropna(subset=["product_description"]).assign(h=d["hs_code"].str[:4]).groupby("h")["product_description"].first()
        hd.insert(1, "example description", hd["heading"].map(lambda h: str(desc.get(h, ""))[:70]))
        st.markdown("**HS heading summary** (4-digit)")
        st.dataframe(
            ui.scaled_table(hd, ["trade_value"], c.scale),
            hide_index=True,
            column_config={
                "trade_value": st.column_config.NumberColumn(f"Value ({c.unit})", format="%.3f"),
                "share_pct": st.column_config.NumberColumn("Share %", format="%.2f"),
                "products": "Codes",
            },
        )
    sec = ta.group_summary(df, "section")
    st.markdown("**HS section summary**")
    st.dataframe(
        ui.scaled_table(sec, ["trade_value"], c.scale),
        hide_index=True,
        column_config={
            "trade_value": st.column_config.NumberColumn(f"Value ({c.unit})", format="%.3f"),
            "share_pct": st.column_config.NumberColumn("Share %", format="%.2f"),
            "products": "Codes",
        },
    )

with tab_cu:
    cop = ta.copper_breakdown(df)
    if not cop.get("available"):
        st.info(cop.get("note") or "No copper records.")
    else:
        t = cop["table"]
        fig = go.Figure()
        if cop["ore_available"]:
            fig.add_trace(go.Bar(x=t["year"], y=t["copper_ore_2603"] / c.scale, name="Copper ores & concentrates (HS 2603)", marker_color=charts.NAVY))
        other = (t["copper_related"].fillna(0) - t["copper_ore_2603"].fillna(0)) if cop["ore_available"] else t["copper_related"]
        fig.add_trace(
            go.Bar(x=t["year"], y=other / c.scale, name="Other copper products (Ch. 74)" if cop["ore_available"] else "Copper-related (Ch. 74)", marker_color=charts.TEAL)
        )
        fig.add_trace(go.Scatter(x=t["year"], y=t["related_share_pct"], name="Copper-related share %", yaxis="y2", mode="lines+markers", line=dict(color=charts.CORAL)))
        fig.update_layout(
            barmode="stack",
            title="Copper and copper-related trade",
            yaxis_title=c.unit,
            yaxis2=dict(title="Share %", overlaying="y", side="right", range=[0, 100], showgrid=False),
            xaxis=dict(dtick=1, tickformat="d"),
            height=420,
        )
        ui.chart(fig)
        if cop.get("note"):
            st.caption(cop["note"])
        cu = df[df["hs_code"].str.startswith(tuple(cop["prefixes_used"]))]
        st.markdown("**Copper-related products in this series**")
        st.dataframe(
            ui.scaled_table(ta.product_ranking(cu), ["trade_value"], c.scale),
            hide_index=True,
            column_config={
                "trade_value": st.column_config.NumberColumn(f"Value ({c.unit})", format="%.3f"),
                "share_pct": st.column_config.NumberColumn("Share of copper %", format="%.1f"),
            },
        )
        st.caption("Copper-related = HS 2603 (copper ores and concentrates) plus HS Chapter 74 (copper and articles thereof, incl. refined cathodes 7403).")

with tab_conc:
    conc = ta.concentration_by_year(df)
    sec_conc = ta.concentration_by_year(df, group_col="section")
    latest = conc.dropna(subset=["hhi_points"]).iloc[-1] if conc["hhi_points"].notna().any() else None
    if latest is not None:
        k = st.columns(4)
        ui.kpi(k[0], f"HHI {int(latest['year'])}", f"{latest['hhi_points']:,.0f}", help=ta.hhi_band(latest["hhi_points"]))
        ui.kpi(k[1], "Products observed", f"{int(latest['products_observed'])}", help="Count of codes with positive value in the year.")
        ui.kpi(
            k[2],
            "Effective number of products",
            f"{latest['effective_products']:.2f}",
            help="1 / HHI: the number of equally sized products that would give the same concentration.",
        )
        ui.kpi(k[3], "Top product share (CR1)", ui.pct(latest["cr1_pct"], signed=False))
    ui.chart(charts.concentration_chart(conc))
    show = conc.copy()
    show["band"] = show["hhi_points"].map(ta.hhi_band)
    st.dataframe(
        show,
        hide_index=True,
        column_config={
            "hhi": st.column_config.NumberColumn("HHI (0–1)", format="%.4f"),
            "hhi_points": st.column_config.NumberColumn("HHI (0–10,000)", format="%.0f"),
            "normalized_hhi": st.column_config.NumberColumn("Normalised HHI", format="%.3f"),
            "effective_products": st.column_config.NumberColumn("Effective products", format="%.2f"),
            "cr1_pct": st.column_config.NumberColumn("CR1 %", format="%.1f"),
            "cr3_pct": st.column_config.NumberColumn("CR3 %", format="%.1f"),
            "cr5_pct": st.column_config.NumberColumn("CR5 %", format="%.1f"),
            "products_ge_1pct": "Products ≥1% share",
        },
    )
    st.markdown("**Diversification across HS sections** (economically broader categories)")
    st.dataframe(
        sec_conc[["year", "products_observed", "hhi_points", "effective_products", "cr1_pct"]].rename(
            columns={"products_observed": "sections observed", "effective_products": "effective sections"}
        ),
        hide_index=True,
        column_config={
            "hhi_points": st.column_config.NumberColumn("Section HHI", format="%.0f"),
            "effective sections": st.column_config.NumberColumn(format="%.2f"),
            "cr1_pct": st.column_config.NumberColumn("Top section %", format="%.1f"),
        },
    )
    with st.expander("How to read these measures", expanded=True):
        st.markdown(
            "- **HHI (Herfindahl–Hirschman Index)** = sum of squared product shares. On a 0–10,000 scale, below 1,500 is commonly treated as "
            "unconcentrated, 1,500–2,500 as moderately and above 2,500 as highly concentrated (bands from the 2010 US Horizontal Merger Guidelines, "
            "used here descriptively).\n"
            "- **Normalised HHI** rescales HHI to 0–1 given the number of products, so years with different product counts can be compared.\n"
            "- **CR1 / CR3 / CR5** are the shares of the largest 1, 3 and 5 products.\n"
            "- **Products observed vs. effective number of products.** A basket can list many codes yet be dominated by one or two. "
            "The effective number (1/HHI) shows how many equally sized products would produce the same concentration, which is a better guide "
            "to genuine diversification than the raw count. Section-level figures show whether diversification spans different industries "
            "or only different codes within the same industry (e.g. several copper products).\n"
            "- Measures depend on the HS level: more digits mean more, smaller product lines."
        )

with tab_map:
    present = c.scope[c.scope["hs_level"] > 0].groupby("classification").agg(records=("hs_code", "size"), codes=("hs_code", "nunique")).reset_index()
    present["label"] = present["classification"].map(lambda x: CLASSIFICATION_LABELS.get(x, x))
    st.markdown("**Classification versions in the active data**")
    st.dataframe(present, hide_index=True)
    if len(present) <= 1:
        st.success("Only one classification version is present, so no mapping is required.")
    else:
        st.warning(
            "Several HS versions are present. They are treated as different products until you record explicit mappings and choose "
            "a target version under 'Classification versions' in the sidebar."
        )
    maps = database.list_mappings(c.engine)
    st.markdown("**Recorded mappings**")
    st.dataframe(maps, hide_index=True)
    with st.form("add_map", clear_on_submit=True):
        st.markdown("Add or update a mapping (one source code → one target code at the same HS level)")
        f1, f2, f3, f4 = st.columns(4)
        cls_opts = sorted(set(CLASSIFICATION_LABELS) | set(present["classification"]))
        from_cl = f1.selectbox("From version", cls_opts, format_func=lambda x: f"{x} ({CLASSIFICATION_LABELS.get(x, x)})")
        from_code = f2.text_input("From code")
        to_cl = f3.selectbox("To version", cls_opts, index=cls_opts.index("H6") if "H6" in cls_opts else 0, format_func=lambda x: f"{x} ({CLASSIFICATION_LABELS.get(x, x)})")
        to_code = f4.text_input("To code")
        source = st.text_input("Mapping source (required)", placeholder="e.g. WCO HS2017–HS2022 correlation table, Table I")
        if st.form_submit_button("Save mapping"):
            try:
                database.add_mapping(c.engine, from_cl, from_code.strip(), to_cl, to_code.strip(), source)
                ui.refresh_data()
                st.success("Mapping saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    up = st.file_uploader(
        "Or upload a mapping table (CSV/Excel with columns from_classification, from_code, to_classification, to_code, source)", type=["csv", "xlsx"], key="map_up"
    )
    if up is not None and st.button("Import mapping table"):
        try:
            mdf, _ = read_table(up.name, up.getvalue())
            need = {"from_classification", "from_code", "to_classification", "to_code", "source"}
            if not need <= set(mdf.columns):
                st.error(f"Missing columns: {', '.join(sorted(need - set(mdf.columns)))}")
            else:
                ok, bad = 0, []
                for i, r in mdf.iterrows():
                    try:
                        database.add_mapping(
                            c.engine, r["from_classification"].strip().upper(), r["from_code"].strip(), r["to_classification"].strip().upper(), r["to_code"].strip(), r["source"]
                        )
                        ok += 1
                    except ValueError as exc:
                        bad.append(f"row {i + 1}: {exc}")
                ui.refresh_data()
                st.success(f"{ok} mappings saved.")
                if bad:
                    st.error("Rejected rows: " + "; ".join(bad[:20]))
        except IngestionError as exc:
            st.error(str(exc))
    if not maps.empty:
        del_id = st.selectbox("Delete mapping", [None] + list(maps["id"]), format_func=lambda x: "—" if x is None else f"#{x}")
        if del_id and st.button("Delete selected mapping"):
            database.delete_mapping(c.engine, int(del_id))
            ui.refresh_data()
            st.rerun()
