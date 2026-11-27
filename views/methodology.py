import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import charts, config, ui
from src.schema import FLOW_LABELS, country_name

c = ui.ctx()
ui.page_header("Methodology & Data Quality", "How the system collects, cleans, analyses and forecasts trade data, and how good the active data are.")

tab_dq, tab_m = st.tabs(["Data quality of active data", "Methodology"])

with tab_dq:
    if not c.has_data:
        ui.empty_state()
    else:
        active = c.datasets[(c.datasets["is_active"]) & (c.datasets["status"] == "complete")]
        st.markdown("**Active datasets**")
        st.dataframe(
            active[
                [
                    "id",
                    "name",
                    "source_label",
                    "is_synthetic",
                    "frequency",
                    "year_min",
                    "year_max",
                    "row_count_raw",
                    "row_count_clean",
                    "row_count_excluded",
                    "pipeline_version",
                    "imported_at",
                ]
            ],
            hide_index=True,
            column_config={"is_synthetic": st.column_config.CheckboxColumn("Synthetic")},
        )
        for _, row in active.iterrows():
            summ = row["cleaning_summary"] if isinstance(row["cleaning_summary"], dict) else {}
            with st.expander(f"#{row['id']} {row['name']} — {len(summ.get('dataset_checks', []))} dataset checks, {summ.get('excluded_rows', 0)} rows excluded"):
                for chk in summ.get("dataset_checks", []):
                    st.markdown(f"- **{chk['check']} ({chk['severity']})** {chk['message']}")
                if summ.get("rule_counts"):
                    st.dataframe(pd.DataFrame(summ["rule_counts"]), hide_index=True)
        d = c.all_data
        st.markdown("**Field completeness (all active records)**")
        fields = ["product_description", "net_weight_kg", "quantity", "quantity_unit", "valuation_basis", "original_record_id"]
        comp = pd.DataFrame({"field": fields, "missing %": [d[f].isna().mean() * 100 for f in fields]})
        comp["assumed valuation basis %"] = ""
        comp.loc[comp["field"] == "valuation_basis", "assumed valuation basis %"] = f"{d['valuation_assumed'].mean() * 100:.1f}"
        st.dataframe(comp, hide_index=True, column_config={"missing %": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100)})
        st.markdown("**Record coverage by series and year** (number of records; blank = no records, not zero trade)")
        cov = d.assign(
            series=[f"{country_name(r)}→{country_name(p)} {FLOW_LABELS.get(f, f)} · L{lv}" for r, p, f, lv in zip(d["reporter_code"], d["partner_code"], d["flow"], d["hs_level"])]
        )
        mat = cov.pivot_table(index="series", columns="year", values="trade_value", aggfunc="size")
        fig = go.Figure(
            go.Heatmap(
                z=mat.values,
                x=[str(x) for x in mat.columns],
                y=list(mat.index),
                colorscale=[[0, "#E6EBF1"], [1, charts.NAVY]],
                hovertemplate="%{y}<br>%{x}: %{z} records<extra></extra>",
                hoverongaps=False,
            )
        )
        fig.update_layout(height=max(260, 40 * len(mat) + 120), title="Records per year")
        ui.chart(fig)
        flagged = d["quality_flags"].notna().sum()
        st.caption(f"{flagged:,} of {len(d):,} active records carry informational or warning flags (e.g. padded HS code, invalid weight).")

with tab_m:
    st.markdown((config.PROJECT_ROOT / "docs" / "methodology.md").read_text(encoding="utf-8").replace("# Methodology\n", "", 1))
