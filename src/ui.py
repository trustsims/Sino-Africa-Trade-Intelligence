from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import streamlit as st

from src import config, database
from src.data_cleaning import apply_classification_mappings
from src.schema import CLASSIFICATION_LABELS, FLOW_LABELS, country_name
from src.trade_analytics import at_level, available_levels, dedupe_across_datasets, default_level, level_label

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SCALES = {"USD": 1.0, "Thousand USD": 1e3, "Million USD": 1e6, "Billion USD": 1e9}
FILTER_KEYS = ["f_freq", "f_currency", "f_scale", "f_years", "f_period", "f_months", "f_reporters", "f_partners", "f_flows", "f_level", "f_sections", "f_chapters", "f_products", "f_harmonize"]


@dataclass
class Context:
    engine: object
    all_data: pd.DataFrame
    scope: pd.DataFrame
    filtered: pd.DataFrame
    level_df: pd.DataFrame
    level: int | None
    filters: dict
    datasets: pd.DataFrame
    settings: dict
    scale: float = 1.0
    unit: str = "USD"
    synthetic: bool = False
    dedup_dropped: int = 0
    harmonize_info: dict = field(default_factory=dict)
    loaded_at: str = ""

    @property
    def has_data(self) -> bool:
        return not self.all_data.empty

    def apply(self, df: pd.DataFrame, skip: tuple = ()) -> pd.DataFrame:
        return apply_filters(df, self.filters, skip)

    def fmt(self, v: float, decimals: int = 1) -> str:
        if v is None or pd.isna(v):
            return "n/a"
        return f"{v / self.scale:,.{decimals}f} {self.unit}"

    def short(self, v: float, decimals: int = 1) -> str:
        if v is None or pd.isna(v):
            return "n/a"
        suffix = {"USD": "", "Thousand USD": "K", "Million USD": "M", "Billion USD": "B"}.get(self.unit, "")
        sign = "-" if v < 0 else ""
        return f"{sign}${abs(v) / self.scale:,.{decimals}f}{suffix}"


@st.cache_resource(show_spinner=False)
def _engine(path: str):
    return database.init_db(database.get_engine(path))


def get_engine():
    return _engine(str(config.db_path()))


@st.cache_data(show_spinner="Loading trade observations…", max_entries=8)
def _load(version: str, db_file: str) -> tuple[pd.DataFrame, int, str]:
    eng = database.get_engine(db_file)
    df = database.load_observations(eng)
    df, dropped = dedupe_across_datasets(df)
    return df, dropped, datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def refresh_data() -> None:
    _load.clear()
    st.cache_data.clear()


def reset_filters() -> None:
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


THEMES = ("dark", "light")


def current_theme() -> str:
    theme = st.session_state.get("ui_theme")
    if theme not in THEMES:
        try:
            theme = database.get_settings(get_engine()).get("ui_theme", "dark")
        except Exception:
            theme = "dark"
        theme = theme if theme in THEMES else "dark"
        st.session_state["ui_theme"] = theme
    return theme


def toggle_theme() -> None:
    theme = "light" if current_theme() == "dark" else "dark"
    st.session_state["ui_theme"] = theme
    if config.read_only():
        return
    try:
        database.set_setting(get_engine(), "ui_theme", theme)
    except Exception:
        config.get_logger().warning("Theme preference could not be saved")


def theme_button(container, key: str, label_dark: str = "☀ Light mode", label_light: str = "☾ Dark mode") -> None:
    dark = current_theme() == "dark"
    container.button(label_dark if dark else label_light, key=key, on_click=toggle_theme, help="Switch the whole site between light and dark mode")


def inject_css() -> None:
    files = ("styles.css", "dark.css", "landing.css")
    css = "\n".join((config.ASSETS_DIR / f).read_text(encoding="utf-8") for f in files if (config.ASSETS_DIR / f).exists())
    st.markdown(f"<style>{css}</style><div class='th-{current_theme()}'></div>", unsafe_allow_html=True)


def _ms(container, key: str, label: str, options: list, default: list, fmt=None, help: str | None = None):
    if key in st.session_state:
        st.session_state[key] = [v for v in st.session_state[key] if v in options]
    else:
        st.session_state[key] = [v for v in default if v in options]
    return container.multiselect(label, options, key=key, format_func=fmt or str, help=help)


def _sel(container, key: str, label: str, options: list, default, fmt=None, help: str | None = None, radio: bool = False):
    if key not in st.session_state or st.session_state[key] not in options:
        st.session_state[key] = default if default in options else options[0]
    widget = container.radio if radio else container.selectbox
    kwargs = {"horizontal": True} if radio else {}
    return widget(label, options, key=key, format_func=fmt or str, help=help, **kwargs)


def period_name(ym: int) -> str:
    return f"{MONTHS[int(ym) % 100 - 1]} {int(ym) // 100}"


def period_label(f: dict) -> str:
    if f.get("period"):
        text = f"{period_name(f['period'][0])}–{period_name(f['period'][1])}"
        if f.get("months"):
            text += " (" + ", ".join(MONTHS[m - 1] for m in sorted(f["months"])) + " only)"
        return text
    if f.get("years"):
        return f"{f['years'][0]}–{f['years'][1]}"
    return "—"


def apply_filters(df: pd.DataFrame, f: dict, skip: tuple = ()) -> pd.DataFrame:
    if df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if "years" not in skip and f.get("years"):
        m &= df["year"].between(f["years"][0], f["years"][1])
    if "period" not in skip and f.get("period") and "month" in df.columns:
        ym = df["year"] * 100 + df["month"].fillna(0)
        m &= ym.between(f["period"][0], f["period"][1])
    if "months" not in skip and f.get("months") and "month" in df.columns:
        m &= df["month"].isin(f["months"])
    if "reporters" not in skip and f.get("reporters"):
        m &= df["reporter_code"].isin(f["reporters"])
    if "partners" not in skip and f.get("partners"):
        m &= df["partner_code"].isin(f["partners"])
    if "flows" not in skip and f.get("flows"):
        m &= df["flow"].isin(f["flows"])
    if "sections" not in skip and f.get("sections"):
        m &= df["section"].isin(f["sections"])
    if "chapters" not in skip and f.get("chapters"):
        m &= df["chapter"].isin(f["chapters"])
    if "products" not in skip and f.get("products"):
        m &= df["hs_code"].isin(f["products"])
    return df[m]


def build_context() -> Context:
    engine = get_engine()
    version = database.data_version(engine)
    df_all, dropped, loaded_at = _load(version, str(database.database_file(engine)))
    settings = database.get_settings(engine)
    datasets = database.list_datasets(engine)
    sb = st.sidebar
    sb.markdown(
        f"<div class='brand'><div class='brand-title'>Sino-African Trade<br>Intelligence</div>"
        f"<div class='brand-sub'>Zambia–China decision support · v{config.APP_VERSION}</div></div>",
        unsafe_allow_html=True,
    )
    with sb.container(key="sb_theme"):
        theme_button(st, "sb_theme_btn")
    filters: dict = {}
    if df_all.empty:
        sb.info("No data imported yet. Open **Data Management** to import your Comtrade CSV.")
        return Context(engine, df_all, df_all, df_all, df_all, None, filters, datasets, settings, loaded_at=loaded_at)
    sb.markdown("<div class='sb-head'>Global filters</div>", unsafe_allow_html=True)
    freqs = sorted(df_all["frequency"].unique())
    freq = (
        _sel(sb, "f_freq", "Frequency", freqs, "A", fmt=lambda v: {"A": "Annual", "M": "Monthly"}[v], radio=True, help="Annual and monthly records are never summed together.")
        if len(freqs) > 1
        else freqs[0]
    )
    if len(freqs) == 1:
        st.session_state["f_freq"] = freq
    d = df_all[df_all["frequency"] == freq]
    currencies = sorted(d["currency"].unique())
    currency = _sel(sb, "f_currency", "Currency", currencies, "USD") if len(currencies) > 1 else currencies[0]
    d = d[d["currency"] == currency]
    scale_label = _sel(
        sb,
        "f_scale",
        "Display unit",
        list(SCALES),
        settings.get("display_scale", "Million USD"),
        help="Changes how values are displayed; calculations always use full-precision values.",
    )
    harm_info = {}
    classes = sorted(d.loc[d["hs_level"] > 0, "classification"].unique())
    mappings = database.list_mappings(engine)
    if len(classes) > 1:
        opts = ["separate"] + classes
        target = _sel(
            sb,
            "f_harmonize",
            "Classification versions",
            opts,
            "separate",
            fmt=lambda v: "Keep versions separate" if v == "separate" else f"Map to {CLASSIFICATION_LABELS.get(v, v)} using recorded mappings",
            help="Different HS versions are distinct products unless you record an explicit mapping (Product Composition page).",
        )
        if target != "separate":
            d, harm_info = apply_classification_mappings(d, mappings, target)
    if freq == "M" and d["month"].notna().any():
        periods = sorted({int(y) * 100 + int(mo) for y, mo in d[["year", "month"]].dropna().itertuples(index=False)})
        cur = st.session_state.get("f_period")
        if not (isinstance(cur, (tuple, list)) and len(cur) == 2 and cur[0] in periods and cur[1] in periods):
            st.session_state["f_period"] = (periods[0], periods[-1])
        if len(periods) > 1:
            pr = sb.select_slider("Period (month and year)", options=periods, key="f_period", format_func=period_name,
                                  help="Choose the first and last month to include.")
        else:
            pr = (periods[0], periods[0])
            sb.caption(f"Period: {period_name(periods[0])}")
        filters["period"] = (int(pr[0]), int(pr[1]))
        filters["years"] = (int(pr[0]) // 100, int(pr[1]) // 100)
        filters["months"] = _ms(sb, "f_months", "Months of the year", list(range(1, 13)), [], fmt=lambda v: MONTHS[v - 1],
                                help="Optional: keep only these calendar months in every year, e.g. Jan–Mar. Leave empty for all months. Forecasting always uses the full monthly series.")
    else:
        years = sorted(d["year"].unique())
        y0, y1 = int(years[0]), int(years[-1])
        if y0 < y1:
            cur = st.session_state.get("f_years", (y0, y1))
            st.session_state["f_years"] = (max(y0, min(cur[0], y1)), min(y1, max(cur[1], y0)))
            yr = sb.slider("Years", y0, y1, key="f_years", step=1)
        else:
            yr = (y0, y1)
            sb.caption(f"Year: {y0}")
        filters["years"] = (int(yr[0]), int(yr[1]))
        if "M" not in freqs:
            sb.caption("Month selection becomes available after monthly data are imported.")
    reporters = sorted(d["reporter_code"].unique(), key=country_name)
    partners = sorted(d["partner_code"].unique(), key=country_name)
    flows = [f for f in FLOW_LABELS if f in set(d["flow"])]
    default_rep = ["894"] if "894" in reporters else reporters[:1]
    filters["reporters"] = _ms(
        sb, "f_reporters", "Reporter", reporters, default_rep, fmt=country_name, help="Country whose customs authority reported the record. Leave empty for all reporters."
    )
    filters["partners"] = _ms(sb, "f_partners", "Partner", partners, [], fmt=country_name, help="Leave empty for all partners.")
    filters["flows"] = _ms(
        sb, "f_flows", "Trade flow", flows, ["X"] if "X" in flows else [], fmt=lambda v: FLOW_LABELS[v], help="Exports and imports are always shown as separate series."
    )
    levels = available_levels(d)
    level = _sel(
        sb, "f_level", "Product level", levels, default_level(levels), fmt=level_label, help="All product statistics use one HS aggregation level to avoid double counting."
    )
    filters["level"] = level
    if level and level > 0:
        lv = d[d["hs_level"] == level]
        filters["sections"] = _ms(sb, "f_sections", "Product category (HS section)", sorted(lv["section"].dropna().unique()), [])
        ch_base = lv[lv["section"].isin(filters["sections"])] if filters["sections"] else lv
        chapters = sorted(ch_base["chapter"].dropna().unique())
        filters["chapters"] = _ms(sb, "f_chapters", "HS chapter", chapters, []) if level > 2 else []
        pr_base = ch_base[ch_base["chapter"].isin(filters["chapters"])] if filters["chapters"] else ch_base
        desc = pr_base.dropna(subset=["product_description"]).groupby("hs_code")["product_description"].first()
        prods = sorted(pr_base["hs_code"].unique())
        filters["products"] = _ms(sb, "f_products", "Products (HS code)", prods, [], fmt=lambda c: f"{c} – {str(desc.get(c, ''))[:48]}")
    else:
        filters["sections"], filters["chapters"], filters["products"] = [], [], []
    c1, c2 = sb.columns(2)
    c1.button("Reset filters", on_click=reset_filters, width="stretch")
    if c2.button("Refresh data", width="stretch", help="Reload records from the database"):
        refresh_data()
        st.rerun()
    sb.caption(f"Data loaded {loaded_at}")
    filters.update({"frequency": freq, "currency": currency, "scale_label": scale_label})
    filtered = apply_filters(d, filters)
    level_df = at_level(filtered, level)
    synthetic = bool(df_all["is_synthetic"].any())
    return Context(engine, df_all, d, filtered, level_df, level, filters, datasets, settings, SCALES[scale_label], scale_label, synthetic, dropped, harm_info, loaded_at)


def ctx() -> Context:
    c = st.session_state.get("_ctx")
    if c is None:
        c = build_context()
        st.session_state["_ctx"] = c
    return c


def page_header(title: str, subtitle: str, rq: str | None = None) -> None:
    rq_html = f"<span class='rq'>{rq}</span>" if rq else ""
    st.markdown(f"<div class='page-head'><h1>{title}</h1><p>{subtitle} {rq_html}</p></div>", unsafe_allow_html=True)


def scope_banner(c: Context, note: str | None = None) -> None:
    if c.synthetic:
        st.warning(
            "**Synthetic demonstration data is active.** Some loaded records are artificially generated and are NOT real trade "
            "statistics. Deactivate the synthetic dataset on the Data Management page before using results.",
            icon="⚠️",
        )
    if not c.has_data:
        return
    active = c.datasets[(c.datasets["is_active"]) & (c.datasets["status"] == "complete")] if not c.datasets.empty else c.datasets
    names = ", ".join(active["name"].astype(str)) if not active.empty else "none"
    sources = ", ".join(sorted(c.all_data["data_source"].dropna().unique()))[:160]
    f = c.filters
    period = period_label(f)
    lvl = level_label(c.level) if c.level is not None else "—"
    freq = {"A": "annual", "M": "monthly"}.get(f.get("frequency"), "")
    st.markdown(
        f"<div class='scope'><b>Active data:</b> {names} &nbsp;·&nbsp; <b>Period:</b> {period} ({freq}) &nbsp;·&nbsp; "
        f"<b>Level:</b> {lvl} &nbsp;·&nbsp; <b>Values:</b> {f.get('currency')} shown in {c.unit} &nbsp;·&nbsp; "
        f"<b>Source:</b> {sources} &nbsp;·&nbsp; <b>Loaded:</b> {c.loaded_at}</div>",
        unsafe_allow_html=True,
    )
    if c.dedup_dropped:
        st.info(f"{c.dedup_dropped} records appear in more than one active dataset; only the most recently imported copy is used.")
    if c.harmonize_info.get("target"):
        hi = c.harmonize_info
        st.info(
            f"Classification harmonisation to {hi['target']}: {hi['mapped_rows']} records mapped using recorded mappings; "
            f"{len(hi['unmapped_codes'])} codes have no mapping and remain in their original version."
        )
    if note:
        st.caption(note)


def empty_state(message: str = "No trade data is loaded yet.") -> None:
    st.markdown(
        f"<div class='empty'><h3>{message}</h3><p>Import <code>{config.PRIMARY_DATASET_NAME}</code> on the "
        "<b>Data Management</b> page or run <code>python scripts\\import_data.py</code>. "
        "A clearly labelled synthetic demo dataset is available there for testing.</p></div>",
        unsafe_allow_html=True,
    )


def kpi(col, label: str, value: str, delta: str | None = None, help: str | None = None, delta_color: str = "normal") -> None:
    col.metric(label, value, delta=delta, help=help, delta_color=delta_color)


def pct(v, signed: bool = True, decimals: int = 1) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    return f"{v:+.{decimals}f}%" if signed else f"{v:.{decimals}f}%"


def scaled_table(df: pd.DataFrame, cols: list[str], scale: float) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out:
            out[c] = out[c] / scale
    return out


def describe_filters(c: Context) -> dict:
    f = c.filters
    names = lambda codes: ", ".join(country_name(x) for x in codes) if codes else "All"
    return {
        "Frequency": {"A": "Annual", "M": "Monthly"}.get(f.get("frequency"), "—"),
        "Period": f"{f['years'][0]}–{f['years'][1]}" if f.get("years") else "—",
        "Reporter": names(f.get("reporters")),
        "Partner": names(f.get("partners")),
        "Trade flow": ", ".join(FLOW_LABELS[x] for x in f.get("flows", [])) or "All",
        "Product level": level_label(c.level) if c.level is not None else "—",
        "HS sections": ", ".join(f.get("sections", [])) or "All",
        "HS chapters": ", ".join(f.get("chapters", [])) or "All",
        "Products": ", ".join(f.get("products", [])) or "All",
        "Currency / display unit": f"{f.get('currency')} / {c.unit}",
    }


def series_picker(df: pd.DataFrame, key: str, container=None, label: str = "Trade series for product analysis") -> tuple[pd.DataFrame, str]:
    container = container or st
    if df.empty:
        return df, ""
    combos = df[["reporter_code", "partner_code", "flow"]].drop_duplicates()
    combos = combos.assign(sort=combos["reporter_code"].map(lambda r: 0 if r == "894" else 1)).sort_values(["sort", "reporter_code", "flow"])
    options = [tuple(r) for r in combos[["reporter_code", "partner_code", "flow"]].itertuples(index=False)]

    def fmt(o):
        return f"{country_name(o[0])} → {country_name(o[1])} · {FLOW_LABELS.get(o[2], o[2])}s ({country_name(o[0])}-reported)"

    if len(options) == 1:
        choice = options[0]
    else:
        choice = container.selectbox(
            label,
            options,
            format_func=fmt,
            key=key,
            help="Product shares and rankings are computed within one reporter, partner and flow so exports and imports are never added together.",
        )
    sub = df[(df["reporter_code"] == choice[0]) & (df["partner_code"] == choice[1]) & (df["flow"] == choice[2])]
    return sub, fmt(choice)


def download_buttons(df: pd.DataFrame, base_name: str, key: str, sheet: str = "data") -> None:
    from src.reporting import to_csv_bytes, to_excel_bytes

    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button("Download CSV", to_csv_bytes(df), f"{base_name}.csv", "text/csv", key=f"{key}_csv", width="stretch")
    c2.download_button(
        "Download Excel", to_excel_bytes({sheet: df}), f"{base_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{key}_xlsx", width="stretch"
    )


def flash(message: str, kind: str = "success") -> None:
    st.session_state["_flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        {"success": st.success, "warning": st.warning, "error": st.error}.get(item[0], st.info)(item[1])


def chart(fig) -> None:
    from src.charts import CONFIG, darken, lighten

    fig = darken(fig) if current_theme() == "dark" else lighten(fig)
    st.plotly_chart(fig, theme=None, config=CONFIG)
