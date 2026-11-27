import io
from datetime import datetime
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd

from src import config


class OptionalDependencyError(Exception):
    pass


SOURCES = [
    ("UN Comtrade Database (United Nations Statistics Division)", "https://comtradeplus.un.org/"),
    ("UN Comtrade API developer portal", "https://comtradedeveloper.un.org/"),
    (
        "International Merchandise Trade Statistics: Concepts and Definitions 2010 (IMTS 2010)",
        "https://www.un.org/en/development/desa/publications/international-merchandise-trade-statistics-concepts-and-definitions-2010-imts-2010.html",
    ),
    ("WCO Harmonized System nomenclature", "https://www.wcoomd.org/en/topics/nomenclature/overview.aspx"),
]


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]) and getattr(out[c].dt, "tz", None) is not None:
            out[c] = out[c].dt.tz_localize(None)
        elif out[c].dtype == object:
            out[c] = out[c].map(lambda v: str(v) if isinstance(v, (dict, list)) else v)
    return out


def to_excel_bytes(sheets: dict[str, pd.DataFrame], metadata: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        if metadata:
            pd.DataFrame({"item": list(metadata.keys()), "value": [str(v) for v in metadata.values()]}).to_excel(writer, sheet_name="About", index=False)
        used = set()
        for name, df in sheets.items():
            if df is None:
                continue
            sheet = "".join(ch for ch in name if ch not in "[]:*?/\\")[:31] or "Sheet"
            base, i = sheet, 1
            while sheet in used:
                sheet = f"{base[:28]}_{i}"
                i += 1
            used.add(sheet)
            _excel_safe(df).to_excel(writer, sheet_name=sheet, index=False)
    return buf.getvalue()


def fig_to_png(fig) -> bytes:
    try:
        return fig.to_image(format="png", width=1200, height=650, scale=2)
    except Exception as exc:
        raise OptionalDependencyError(
            "Server-side PNG export needs the optional 'kaleido' package (pip install kaleido) and, for kaleido 1.x, a local "
            "Chrome/Chromium. You can always use the camera icon in each chart's toolbar to download a PNG directly from the browser. "
            f"Details: {str(exc)[:160]}"
        ) from exc


PDF_REPLACEMENTS = {"→": "->", "−": "-", "Σ": "sum of ", "⚠": "Warning:", "≤": "<=", "≥": ">=", "…": "..."}


def pdf_text(text) -> str:
    s = str(text)
    for k, v in PDF_REPLACEMENTS.items():
        s = s.replace(k, v)
    return s.encode("cp1252", errors="replace").decode("cp1252")


def _p(text: str, style):
    from reportlab.platypus import Paragraph

    return Paragraph(escape(pdf_text(text)), style)


def _table(df: pd.DataFrame, styles, col_widths=None, max_rows: int = 25):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    d = df.head(max_rows)
    data = [[_p(c, styles["cellb"]) for c in d.columns]]
    for row in d.itertuples(index=False):
        data.append([_p(v, styles["cell"]) for v in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#13315C")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C8D1DC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F9")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t


def _line_chart(series: dict[str, pd.Series], title: str, y_label: str):
    from reportlab.graphics.charts.legends import Legend
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    palette = ["#13315C", "#1F9E9A", "#8DA9C4", "#E07A5F", "#6B7A8F"]
    d = Drawing(480, 220)
    d.add(String(0, 205, title, fontName="Helvetica-Bold", fontSize=10, fillColor=colors.HexColor("#13315C")))
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 50, 30, 300, 160
    data, names = [], []
    for name, s in series.items():
        s = s.dropna()
        if len(s):
            data.append([(float(x), float(y)) for x, y in zip(s.index, s.values)])
            names.append(name)
    if not data:
        return None
    lp.data = data
    for i in range(len(data)):
        lp.lines[i].strokeColor = colors.HexColor(palette[i % len(palette)])
        lp.lines[i].strokeWidth = 1.8
    xs = [p[0] for line in data for p in line]
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = min(xs), max(xs)
    lp.xValueAxis.valueStep = max(1, round((max(xs) - min(xs)) / 8)) if max(xs) > min(xs) else 1
    lp.xValueAxis.labelTextFormat = "%d"
    lp.xValueAxis.labels.fontSize = 7
    lp.yValueAxis.labels.fontSize = 7
    lp.yValueAxis.labelTextFormat = "%.0f"
    lp.yValueAxis.valueMin = 0
    d.add(lp)
    d.add(String(0, 12, y_label, fontName="Helvetica", fontSize=7))
    lg = Legend()
    lg.x, lg.y = 360, 180
    lg.fontSize = 7
    lg.colorNamePairs = [(colors.HexColor(palette[i % len(palette)]), pdf_text(names[i])[:38]) for i in range(len(names))]
    d.add(lg)
    return d


def _bar_chart(labels: list[str], values: list[float], title: str):
    from reportlab.graphics.charts.barcharts import HorizontalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    n = len(values)
    h = 40 + 16 * n
    d = Drawing(480, h + 20)
    d.add(String(0, h + 8, title, fontName="Helvetica-Bold", fontSize=10, fillColor=colors.HexColor("#13315C")))
    bc = HorizontalBarChart()
    bc.x, bc.y, bc.width, bc.height = 190, 15, 270, h - 20
    bc.data = [list(reversed(values))]
    bc.categoryAxis.categoryNames = [pdf_text(lbl)[:42] for lbl in reversed(labels)]
    bc.categoryAxis.labels.fontSize = 6.5
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.valueMin = 0
    bc.bars[0].fillColor = colors.HexColor("#1F9E9A")
    d.add(bc)
    return d


def build_pdf_report(ctx: dict) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise OptionalDependencyError("PDF reports need the 'reportlab' package: pip install reportlab") from exc
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("t", parent=base["Title"], textColor=colors.HexColor("#13315C"), fontSize=17, leading=21),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=colors.HexColor("#13315C"), fontSize=12.5, spaceBefore=10),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=9, leading=12.5),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=7.5, leading=10, textColor=colors.HexColor("#4A5568")),
        "warn": ParagraphStyle("w", parent=base["BodyText"], fontSize=9, leading=12, textColor=colors.HexColor("#9B2C2C")),
        "cell": ParagraphStyle("c", parent=base["BodyText"], fontSize=7, leading=8.5),
        "cellb": ParagraphStyle("cb", parent=base["BodyText"], fontSize=7, leading=8.5, textColor=colors.white, fontName="Helvetica-Bold"),
    }
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm, title=ctx.get("title", config.APP_TITLE), author=config.APP_TITLE
    )
    el = [
        Paragraph(escape(pdf_text(ctx.get("title", config.APP_TITLE))), styles["title"]),
        _p(config.APP_SUBTITLE, styles["small"]),
        _p(f"Generated {ctx.get('generated_at', datetime.now().strftime('%Y-%m-%d %H:%M'))} · Application v{config.APP_VERSION}", styles["small"]),
        Spacer(1, 6),
    ]
    if ctx.get("synthetic"):
        el.append(_p("WARNING: the active data include SYNTHETIC demonstration records. Figures in this report are NOT real trade statistics.", styles["warn"]))
    el.append(Paragraph("Scope and filters", styles["h2"]))
    scope = pd.DataFrame({"Item": list(ctx.get("filters", {}).keys()), "Value": [str(v) for v in ctx.get("filters", {}).values()]})
    el.append(_table(scope, styles, [5 * cm, 12 * cm]))
    if ctx.get("datasets") is not None and len(ctx["datasets"]):
        el.append(Spacer(1, 6))
        el.append(_table(ctx["datasets"], styles))
    if ctx.get("kpis"):
        el.append(Paragraph("Key indicators", styles["h2"]))
        el.append(_table(pd.DataFrame(ctx["kpis"], columns=["Indicator", "Value"]), styles, [8 * cm, 9 * cm]))
    if ctx.get("observations"):
        el.append(Paragraph("Key findings (calculated from the active dataset)", styles["h2"]))
        for o in ctx["observations"]:
            el.append(_p(f"• {o}", styles["body"]))
    annual = ctx.get("annual")
    scale, scale_label = ctx.get("scale", 1.0), ctx.get("scale_label", "USD")
    if annual is not None and not annual.empty:
        el.append(Paragraph("Annual trade values", styles["h2"]))
        series = {name: grp.set_index("year")["trade_value"] / scale for name, grp in annual.groupby("series")}
        chart = _line_chart(series, "Annual trade value", scale_label)
        if chart is not None:
            el.append(chart)
        t = annual[["series", "year", "trade_value", "yoy_pct"]].copy()
        t["trade_value"] = (t["trade_value"] / scale).map(lambda v: f"{v:,.2f}")
        t["yoy_pct"] = t["yoy_pct"].map(lambda v: "n/a" if pd.isna(v) else f"{v:+.1f}%")
        t.columns = ["Series", "Year", f"Value ({scale_label})", "YoY growth"]
        el.append(_table(t, styles, max_rows=40))
    top = ctx.get("top_products")
    if top is not None and not top.empty:
        el.append(Paragraph("Top products in the selected period", styles["h2"]))
        el.append(_bar_chart(list(top["product"]), [float(v) / scale for v in top["trade_value"]], f"Trade value ({scale_label})"))
        t = top[["rank", "product", "trade_value", "share_pct"]].copy()
        t["trade_value"] = (t["trade_value"] / scale).map(lambda v: f"{v:,.2f}")
        t["share_pct"] = t["share_pct"].map(lambda v: f"{v:.1f}%")
        t.columns = ["Rank", "Product", f"Value ({scale_label})", "Share"]
        el.append(_table(t, styles, [1.2 * cm, 10 * cm, 3.2 * cm, 2.2 * cm]))
    conc = ctx.get("concentration")
    if conc is not None and not conc.empty:
        el.append(Paragraph("Export concentration", styles["h2"]))
        t = conc[["year", "products_observed", "hhi_points", "effective_products", "cr1_pct", "cr3_pct"]].copy()
        for c in ("hhi_points", "effective_products", "cr1_pct", "cr3_pct"):
            t[c] = t[c].map(lambda v: "n/a" if pd.isna(v) else f"{v:,.1f}")
        t.columns = ["Year", "Products", "HHI (0-10,000)", "Effective no. products", "CR1 %", "CR3 %"]
        el.append(_table(t, styles))
        el.append(
            _p(
                "HHI is the sum of squared product shares; values above 2,500 indicate high concentration. The effective number of products (1/HHI) "
                "measures diversification better than a simple count.",
                styles["small"],
            )
        )
    mirror = ctx.get("mirror")
    if mirror:
        el.append(Paragraph("Mirror-trade comparison", styles["h2"]))
        el.append(_p(mirror["title"], styles["body"]))
        sm = mirror.get("summary", {})
        rows = [
            ("Records compared", sm.get("records_total")),
            ("Matched records", sm.get("records_matched")),
            ("Match rate", _pct(sm.get("match_rate_pct"))),
            ("Aggregate discrepancy (partner − reporter)", _pct(sm.get("aggregate_pct_discrepancy"), True)),
            ("Median record discrepancy", _pct(sm.get("median_pct_discrepancy"), True)),
            ("Records within ±10%", _pct(sm.get("share_within_10pct"))),
        ]
        el.append(_table(pd.DataFrame(rows, columns=["Measure", "Value"]), styles, [9 * cm, 8 * cm]))
        if mirror.get("annual") is not None and not mirror["annual"].empty:
            t = mirror["annual"][["year", "value_a", "value_b", "abs_discrepancy", "pct_discrepancy"]].copy()
            for c in ("value_a", "value_b", "abs_discrepancy"):
                t[c] = (t[c] / scale).map(lambda v: f"{v:,.2f}")
            t["pct_discrepancy"] = t["pct_discrepancy"].map(lambda v: _pct(v, True))
            t.columns = ["Year", f"{mirror['a_label']} ({scale_label})", f"{mirror['b_label']} ({scale_label})", "Difference", "Difference %"]
            el.append(Spacer(1, 4))
            el.append(_table(t, styles))
        el.append(
            _p(
                "Discrepancies are not evidence of misreporting: CIF/FOB valuation, timing, re-exports, classification and partner attribution all "
                "produce legitimate differences between mirror statistics.",
                styles["small"],
            )
        )
    fc = ctx.get("forecast")
    if fc:
        el.append(Paragraph("Copper export forecast", styles["h2"]))
        el.append(_p(f"Series: {fc['label']}. Selected model: {fc['selected']}. {fc['reason']}", styles["body"]))
        if fc.get("metrics") is not None and not fc["metrics"].empty:
            t = fc["metrics"][["model", "n_test", "MAE", "RMSE", "MASE", "MAPE"]].copy()
            for c in ("MAE", "RMSE"):
                t[c] = (t[c] / scale).map(lambda v: "n/a" if pd.isna(v) else f"{v:,.2f}")
            for c in ("MASE",):
                t[c] = t[c].map(lambda v: "n/a" if pd.isna(v) else f"{v:.3f}")
            t["MAPE"] = t["MAPE"].map(lambda v: "n/a" if pd.isna(v) else f"{v:.1f}%")
            t.columns = ["Model", "Test points", f"MAE ({scale_label})", f"RMSE ({scale_label})", "MASE", "MAPE"]
            el.append(_table(t, styles))
        if fc.get("table") is not None and not fc["table"].empty:
            t = fc["table"][["period", "forecast", "lower", "upper"]].copy()
            for c in ("forecast", "lower", "upper"):
                t[c] = (t[c] / scale).map(lambda v: "n/a" if pd.isna(v) else f"{v:,.2f}")
            t.columns = ["Period", f"Forecast ({scale_label})", f"Lower {fc['level']}%", f"Upper {fc['level']}%"]
            el.append(Spacer(1, 4))
            el.append(_table(t, styles))
        for w in fc.get("warnings", []):
            el.append(_p(f"Warning: {w}", styles["small"]))
        el.append(_p(fc.get("disclaimer", ""), styles["small"]))
    el.append(PageBreak())
    el.append(Paragraph("Methodology summary", styles["h2"]))
    for line in METHOD_LINES:
        el.append(_p(f"• {line}", styles["body"]))
    el.append(Paragraph("Data-quality warnings and limitations", styles["h2"]))
    for w in ctx.get("warnings", []) or ["No dataset-level warnings for the active data."]:
        el.append(_p(f"• {w}", styles["body"]))
    for w in LIMITATIONS:
        el.append(_p(f"• {w}", styles["body"]))
    el.append(Paragraph("Sources", styles["h2"]))
    for name, url in SOURCES:
        el.append(_p(f"{name}: {url}", styles["small"]))
    doc.build(el)
    return buf.getvalue()


def _pct(v, signed: bool = False) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


METHOD_LINES = [
    "Values are summed only within one currency, one frequency (annual or monthly) and one HS aggregation level, so totals are never double counted across levels.",
    "Year-on-year growth = (V_t − V_t−1) / V_t−1 × 100, calculated only between consecutive years; undefined when V_t−1 = 0.",
    "Compound annual growth = (V_end / V_start)^(1/(end − start)) − 1, defined only for positive start and end values.",
    "Concentration: HHI = Σ s_i² over product shares s_i; CRk = share of the k largest products; effective number of products = 1/HHI.",
    "Mirror comparison: absolute discrepancy = partner-reported value − reporter-reported value; percentage discrepancy divides by the reporter value and is undefined when it is zero.",
    "Forecasting: naive, drift, linear trend and ARIMA (plus seasonal naive and SARIMA for long monthly series) are compared with rolling-origin, one-step-ahead evaluation on an expanding window; the model with the lowest MASE is chosen, unless a simpler model is within the parsimony tolerance.",
]

LIMITATIONS = [
    "Official trade statistics are revised over time; results reflect the data as imported on the stated dates.",
    "Absent records are treated as missing, not as zero trade.",
    "Forecasts rely only on the historical series and do not model copper prices, production or policy.",
]
