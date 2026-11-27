import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

NAVY = "#13315C"
TEAL = "#1F9E9A"
SKY = "#8DA9C4"
CORAL = "#D1495B"
SLATE = "#5C6B7F"
GOLD = "#C9A227"
PALETTE = [NAVY, TEAL, SKY, "#0B6E8A", GOLD, SLATE, "#7FB7BE", CORAL, "#2E4A7D", "#A3B9C9"]

pio.templates["sati"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Inter, Segoe UI, Helvetica, Arial, sans-serif", size=13, color="#1A2B42"),
        colorway=PALETTE,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        title=dict(font=dict(size=15, color=NAVY), x=0.01, xanchor="left", xref="container", y=0.985, yref="container", yanchor="top"),
        xaxis=dict(gridcolor="#E6EBF1", linecolor="#C8D1DC", zerolinecolor="#C8D1DC", automargin=True),
        yaxis=dict(gridcolor="#E6EBF1", linecolor="#C8D1DC", zerolinecolor="#C8D1DC", automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font=dict(size=11)),
        margin=dict(l=10, r=10, t=72, b=10),
        hoverlabel=dict(font_size=12),
    )
)
pio.templates.default = "sati"

DARK_SWAP = {"#13315C": "#8FB4E6", "#0B2545": "#6F95C8", "#2E4A7D": "#7C9CD0", "#0B6E8A": "#3BA7C4", "#1A2B42": "#DCE5EE",
             "#5C6B7F": "#9AA9BA", "#E6EBF1": "#24394D", "#C8D1DC": "#34506A", "#A3B9C9": "#6F8AA3"}

pio.templates["sati_dark"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Inter, Segoe UI, Helvetica, Arial, sans-serif", size=13, color="#DCE5EE"),
        colorway=[DARK_SWAP.get(c, c) for c in PALETTE],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0F1E2D",
        title=dict(font=dict(size=15, color="#F2F6F8"), x=0.01, xanchor="left", xref="container", y=0.985, yref="container", yanchor="top"),
        xaxis=dict(gridcolor="#22374B", linecolor="#34506A", zerolinecolor="#34506A", automargin=True),
        yaxis=dict(gridcolor="#22374B", linecolor="#34506A", zerolinecolor="#34506A", automargin=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font=dict(size=11)),
        margin=dict(l=10, r=10, t=72, b=10),
        hoverlabel=dict(font_size=12, bgcolor="#16293C", bordercolor="#34506A", font_color="#F2F6F8"),
    )
)


def darken(fig: go.Figure) -> go.Figure:
    text = fig.to_json()
    for light, dark in DARK_SWAP.items():
        text = text.replace(light, dark).replace(light.lower(), dark)
    out = pio.from_json(text)
    out.update_layout(template=pio.templates["sati_dark"], paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0F1E2D",
                      font_color="#DCE5EE", title_font_color="#F2F6F8", legend_font_color="#DCE5EE",
                      hoverlabel=dict(bgcolor="#16293C", bordercolor="#34506A", font_color="#F2F6F8"))
    out.update_xaxes(gridcolor="#22374B", linecolor="#34506A", zerolinecolor="#34506A", tickfont_color="#B8C6D3", title_font_color="#DCE5EE")
    out.update_yaxes(gridcolor="#22374B", linecolor="#34506A", zerolinecolor="#34506A", tickfont_color="#B8C6D3", title_font_color="#DCE5EE")
    for a in out.layout.annotations or ():
        if a.font is None or a.font.color in (None, "#1A2B42", "#DCE5EE"):
            a.font = dict(color="#DCE5EE", size=a.font.size if a.font else None)
    return out


def lighten(fig: go.Figure) -> go.Figure:
    fig.update_layout(template=pio.templates["sati"], paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FFFFFF")
    return fig
CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}


def _scaled(df: pd.DataFrame, col: str, scale: float) -> pd.DataFrame:
    out = df.copy()
    out[col] = out[col] / scale
    return out


def trend_lines(annual: pd.DataFrame, scale: float, unit: str, title: str = "Annual trade value") -> go.Figure:
    fig = go.Figure()
    for i, (name, grp) in enumerate(annual.groupby("series")):
        g = grp.sort_values("year")
        fig.add_trace(
            go.Scatter(
                x=g["year"],
                y=g["trade_value"] / scale,
                name=name,
                mode="lines+markers",
                line=dict(width=2.5, color=PALETTE[i % len(PALETTE)]),
                hovertemplate="%{x}: %{y:,.2f} " + unit + "<extra>" + name + "</extra>",
            )
        )
    fig.update_layout(title=title, yaxis_title=unit, xaxis=dict(dtick=1, tickformat="d"), height=380)
    return fig


def period_lines(series: pd.DataFrame, scale: float, unit: str, title: str) -> go.Figure:
    fig = go.Figure()
    for i, (name, grp) in enumerate(series.groupby("series")):
        fig.add_trace(go.Scatter(x=grp["date"], y=grp["trade_value"] / scale, name=name, mode="lines", line=dict(width=2, color=PALETTE[i % len(PALETTE)])))
    fig.update_layout(title=title, yaxis_title=unit, height=380)
    return fig


def growth_bars(annual: pd.DataFrame, title: str = "Year-on-year growth (%)") -> go.Figure:
    fig = go.Figure()
    for i, (name, grp) in enumerate(annual.groupby("series")):
        g = grp.dropna(subset=["yoy_pct"])
        colors = [TEAL if v >= 0 else CORAL for v in g["yoy_pct"]] if annual["series"].nunique() == 1 else PALETTE[i % len(PALETTE)]
        fig.add_trace(go.Bar(x=g["year"], y=g["yoy_pct"], name=name, marker_color=colors, hovertemplate="%{x}: %{y:+.1f}%<extra>" + name + "</extra>"))
    fig.update_layout(title=title, yaxis_title="%", xaxis=dict(dtick=1, tickformat="d"), barmode="group", height=340)
    return fig


def ranking_bar(rank: pd.DataFrame, scale: float, unit: str, title: str) -> go.Figure:
    r = rank.sort_values("trade_value")
    fig = go.Figure(
        go.Bar(
            x=r["trade_value"] / scale,
            y=r["product"],
            orientation="h",
            marker_color=TEAL,
            customdata=r["share_pct"],
            hovertemplate="%{y}<br>%{x:,.2f} " + unit + " (%{customdata:.1f}%)<extra></extra>",
        )
    )
    fig.update_layout(title=title, xaxis_title=unit, height=max(320, 28 * len(r) + 120), yaxis=dict(tickfont=dict(size=11)))
    return fig


def stacked_composition(df: pd.DataFrame, group_col: str, scale: float, unit: str, title: str, top_n: int = 8, share: bool = False) -> go.Figure:
    g = df.groupby(["year", group_col])["trade_value"].sum().reset_index()
    top = g.groupby(group_col)["trade_value"].sum().nlargest(top_n).index
    g[group_col] = np.where(g[group_col].isin(top), g[group_col], "Other")
    g = g.groupby(["year", group_col])["trade_value"].sum().reset_index()
    if share:
        g["trade_value"] = g["trade_value"] / g.groupby("year")["trade_value"].transform("sum") * 100
    order = list(g.groupby(group_col)["trade_value"].sum().sort_values(ascending=False).index)
    if "Other" in order:
        order.remove("Other")
        order.append("Other")
    fig = go.Figure()
    for i, name in enumerate(order):
        sub = g[g[group_col] == name]
        y = sub["trade_value"] if share else sub["trade_value"] / scale
        fig.add_trace(go.Bar(x=sub["year"], y=y, name=str(name)[:45], marker_color=PALETTE[i % len(PALETTE)] if name != "Other" else "#C8D1DC"))
    fig.update_layout(
        barmode="stack",
        title=title,
        yaxis_title="% of total" if share else unit,
        xaxis=dict(dtick=1, tickformat="d"),
        height=440,
        legend=dict(orientation="h", y=-0.25, yanchor="top"),
    )
    return fig


def heatmap(matrix: pd.DataFrame, scale: float, unit: str, title: str) -> go.Figure:
    z = matrix.values / scale
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[str(c) for c in matrix.columns],
            y=[str(i)[:55] for i in matrix.index],
            colorscale=[[0, "#F3F6F9"], [0.5, SKY], [1, NAVY]],
            colorbar=dict(title=unit),
            hovertemplate="%{y}<br>%{x}: %{z:,.2f} " + unit + "<extra></extra>",
            hoverongaps=False,
        )
    )
    fig.update_layout(title=title, height=max(360, 26 * len(matrix) + 140), yaxis=dict(autorange="reversed", tickfont=dict(size=11)))
    return fig


def scatter(df: pd.DataFrame, x: str, y: str, label: str, title: str, x_title: str, y_title: str, log: bool = True, size: str | None = None) -> go.Figure:
    d = df.dropna(subset=[x, y])
    if log:
        d = d[(d[x] > 0) & (d[y] > 0)]
    sizes = None
    if size and size in d:
        s = d[size].astype(float)
        sizes = 8 + 30 * (s - s.min()) / (s.max() - s.min()) if s.max() > s.min() else 12
    fig = go.Figure(
        go.Scatter(
            x=d[x],
            y=d[y],
            mode="markers",
            text=d[label],
            marker=dict(color=TEAL, size=sizes if sizes is not None else 10, line=dict(color=NAVY, width=1), opacity=0.8),
            hovertemplate="%{text}<br>" + x_title + ": %{x:,.3s}<br>" + y_title + ": %{y:,.3s}<extra></extra>",
        )
    )
    fig.update_layout(title=title, xaxis_title=x_title, yaxis_title=y_title, height=440)
    if log:
        fig.update_xaxes(type="log")
        fig.update_yaxes(type="log")
    return fig


def concentration_chart(conc: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=conc["year"], y=conc["hhi_points"], name="HHI (0–10,000)", mode="lines+markers", line=dict(color=NAVY, width=2.5)))
    fig.add_trace(
        go.Scatter(x=conc["year"], y=conc["effective_products"], name="Effective number of products", mode="lines+markers", line=dict(color=TEAL, width=2, dash="dot"), yaxis="y2")
    )
    fig.add_hrect(y0=2500, y1=10000, fillcolor=CORAL, opacity=0.06, line_width=0)
    fig.add_hline(y=2500, line=dict(color=CORAL, dash="dash", width=1), annotation_text="High concentration (2,500)", annotation_position="top left")
    ymax = max(3000.0, float(np.nanmax(conc["hhi_points"])) * 1.15) if conc["hhi_points"].notna().any() else 10000
    fig.update_layout(
        title="Concentration of the trade basket",
        yaxis=dict(title="HHI", range=[0, ymax]),
        yaxis2=dict(title="Effective products", overlaying="y", side="right", showgrid=False, rangemode="tozero"),
        xaxis=dict(dtick=1, tickformat="d"),
        height=380,
    )
    return fig


def mirror_bars(annual: pd.DataFrame, a_label: str, b_label: str, scale: float, unit: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=annual["year"], y=annual["value_a"] / scale, name=a_label, marker_color=NAVY))
    fig.add_trace(go.Bar(x=annual["year"], y=annual["value_b"] / scale, name=b_label, marker_color=TEAL))
    fig.add_trace(go.Scatter(x=annual["year"], y=annual["pct_discrepancy"], name="Discrepancy %", yaxis="y2", mode="lines+markers", line=dict(color=CORAL, width=2)))
    fig.update_layout(
        barmode="group",
        title="Matched values by year and percentage discrepancy",
        yaxis_title=unit,
        yaxis2=dict(title="Discrepancy %", overlaying="y", side="right", showgrid=False, zeroline=True, zerolinecolor=CORAL, ticksuffix="%", tickformat=".0f", rangemode="tozero"),
        xaxis=dict(dtick=1, tickformat="d"),
        height=420,
    )
    return fig


def mirror_scatter(records: pd.DataFrame, a_label: str, b_label: str, scale: float, unit: str) -> go.Figure:
    d = records[(records["match_status"] == "matched") & (records["value_a"] > 0) & (records["value_b"] > 0)]
    fig = go.Figure()
    if d.empty:
        return fig
    lo = min(d["value_a"].min(), d["value_b"].min()) / scale
    hi = max(d["value_a"].max(), d["value_b"].max()) / scale
    fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="Perfect agreement", line=dict(color=SLATE, dash="dash")))
    fig.add_trace(
        go.Scatter(
            x=d["value_a"] / scale,
            y=d["value_b"] / scale,
            mode="markers",
            name="Product-year records",
            text=d["product"] + " (" + d["period"].astype(str) + ")",
            marker=dict(color=TEAL, size=9, line=dict(color=NAVY, width=1)),
            hovertemplate="%{text}<br>" + a_label + ": %{x:,.3f}<br>" + b_label + ": %{y:,.3f}<extra></extra>",
        )
    )
    fig.update_layout(title="Record-level agreement (log scales)", xaxis_title=f"{a_label} ({unit})", yaxis_title=f"{b_label} ({unit})", height=440)
    fig.update_xaxes(type="log")
    fig.update_yaxes(type="log")
    return fig


def forecast_chart(result: dict, scale: float, unit: str, frequency: str, show_fitted: bool, compare_models: list[str], level: int) -> go.Figure:
    from src.forecasting import period_to_timestamp

    used = result["used"]
    hist = result["series"]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=period_to_timestamp([str(i) for i in hist.index], frequency),
            y=hist.values / scale,
            name="Historical observations",
            mode="lines+markers",
            line=dict(color=NAVY, width=2.5),
        )
    )
    if show_fitted and result.get("fitted") is not None:
        f = result["fitted"]
        fig.add_trace(
            go.Scatter(
                x=period_to_timestamp(f["period"], frequency),
                y=f["fitted"] / scale,
                name=f"In-sample fitted ({result['selected']})",
                mode="lines",
                line=dict(color=SLATE, dash="dot", width=1.5),
            )
        )
    bt = result.get("backtest")
    if bt is not None and not bt.empty and result["selected"] in bt:
        fig.add_trace(
            go.Scatter(
                x=period_to_timestamp(bt["period"], frequency),
                y=bt[result["selected"]] / scale,
                name=f"Out-of-sample backtest ({result['selected']})",
                mode="markers",
                marker=dict(symbol="diamond-open", size=10, color=GOLD, line=dict(width=2)),
            )
        )
    fc = result["forecasts"]
    sel = fc[fc["model"] == result["selected"]]
    last_x = period_to_timestamp([str(used.index[-1])], frequency)
    xs = period_to_timestamp(sel["period"], frequency)
    fig.add_trace(
        go.Scatter(
            x=xs + xs[::-1],
            y=list(sel["upper"] / scale) + list(sel["lower"] / scale)[::-1],
            fill="toself",
            fillcolor="rgba(31,158,154,0.15)",
            line=dict(width=0),
            mode="lines",
            name=f"{level}% prediction interval",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=last_x + xs,
            y=[used.values[-1] / scale] + list(sel["forecast"] / scale),
            name=f"Forecast ({result['selected']})",
            mode="lines+markers",
            line=dict(color=TEAL, width=3, dash="dash"),
        )
    )
    for i, name in enumerate(compare_models):
        if name == result["selected"]:
            continue
        other = fc[fc["model"] == name]
        if other.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=last_x + period_to_timestamp(other["period"], frequency),
                y=[used.values[-1] / scale] + list(other["forecast"] / scale),
                name=f"{name} (comparison)",
                mode="lines",
                line=dict(width=1.5, dash="dot", color=PALETTE[(i + 3) % len(PALETTE)]),
            )
        )
    fig.add_vline(x=last_x[0], line=dict(color="#A0AEC0", dash="dot", width=1))
    fig.update_layout(title="Historical series, backtest and forecast", yaxis_title=unit, height=470, hovermode="x unified")
    return fig


SCENARIO_COLORS = [SLATE, GOLD, CORAL, "#0B6E8A", "#7FB7BE"]


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def outlook_chart(history: pd.Series, result: dict | None, scenarios: pd.DataFrame | None, scale: float, unit: str, interval: int, title: str, show_models: bool = True) -> go.Figure:
    fig = go.Figure()
    hx = [int(i) for i in history.index]
    last_x, last_y = hx[-1], float(history.values[-1]) / scale
    if result is not None and result.get("status") not in ("insufficient", "failed"):
        fc = result["forecasts"]
        sel = fc[fc["model"] == result["selected"]]
        xs = [int(p) for p in sel["period"]]
        fig.add_trace(go.Scatter(x=xs + xs[::-1], y=list(sel["upper"] / scale) + list(sel["lower"] / scale)[::-1], fill="toself",
                                 fillcolor="rgba(31,158,154,0.13)", line=dict(width=0), mode="lines", name=f"{interval}% interval ({result['selected']})", hoverinfo="skip"))
        if show_models:
            for i, (name, g) in enumerate(fc.groupby("model", sort=False)):
                if name == result["selected"]:
                    continue
                fig.add_trace(go.Scatter(x=[last_x] + [int(p) for p in g["period"]], y=[last_y] + list(g["forecast"] / scale), mode="lines",
                                         name=f"Statistical: {name}", line=dict(width=1.3, dash="dot", color=PALETTE[(i + 2) % len(PALETTE)])))
        fig.add_trace(go.Scatter(x=[last_x] + xs, y=[last_y] + list(sel["forecast"] / scale), mode="lines", name=f"Statistical: {result['selected']} (selected)",
                                 line=dict(color=TEAL, width=2.6, dash="dash")))
    if scenarios is not None and not scenarios.empty:
        for i, (name, g) in enumerate(scenarios.groupby("scenario", sort=False)):
            col = SCENARIO_COLORS[i % len(SCENARIO_COLORS)]
            gx = [int(v) for v in g["year"]]
            fig.add_trace(go.Scatter(x=gx + gx[::-1], y=list(g["high"] / scale) + list(g["low"] / scale)[::-1], fill="toself", fillcolor=_rgba(col, 0.10),
                                     line=dict(width=0), mode="lines", showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=[last_x] + gx, y=[last_y] + list(g["value"] / scale), mode="lines", name=name, line=dict(color=col, width=2.4)))
    fig.add_trace(go.Scatter(x=hx, y=history.values / scale, mode="lines+markers", name="Observed", line=dict(color=NAVY, width=2.6)))
    fig.add_vline(x=last_x, line=dict(color="#A0AEC0", dash="dot", width=1))
    for k in (5, 10):
        fig.add_vline(x=last_x + k, line=dict(color="#C8D1DC", dash="dot", width=1), annotation_text=f"{k} years", annotation_position="top")
    fig.update_layout(title=title, yaxis_title=unit, height=500, hovermode="x unified", xaxis=dict(dtick=2))
    return fig


def balance_chart(history: pd.Series, paths: pd.DataFrame, scale: float, unit: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[int(i) for i in history.index], y=history.values / scale, name="Observed balance",
                         marker_color=[TEAL if v >= 0 else CORAL for v in history.values]))
    for i, (basis, g) in enumerate(paths.groupby("basis", sort=False)):
        fig.add_trace(go.Scatter(x=g["year"], y=g["balance"] / scale, mode="lines+markers", name=f"Projected ({basis.lower()})",
                                 line=dict(color=[NAVY, GOLD][i % 2], dash="dash", width=2)))
    fig.add_hline(y=0, line=dict(color="#A0AEC0", width=1))
    fig.update_layout(title="Zambia's trade balance with China: observed and projected", yaxis_title=unit, height=420, hovermode="x unified", xaxis=dict(dtick=2))
    return fig
