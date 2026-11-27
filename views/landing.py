from html import escape

import pandas as pd
import streamlit as st

from src import ui
from src.landing_visual import LOGO, corner, world_img

c = ui.ctx()

theme = ui.current_theme()

st.markdown(f"<div class='lp-root lp-{theme}'></div>{corner('africa')}{corner('china')}", unsafe_allow_html=True)

with st.container(key="lp_nav"):
    left, mode, right = st.columns([4, 0.55, 1.1], vertical_alignment="center")
    left.markdown(
        f"<div class='lp-brand'>{LOGO}<div class='lp-brand-name'>SINO-AFRICAN<span>TRADE INTELLIGENCE</span></div>"
        "<div class='lp-brand-sep'></div><div class='lp-brand-pair'>ZAMBIA <i>×</i> CHINA</div></div>",
        unsafe_allow_html=True,
    )
    with mode.container(key="lp_theme_btn"):
        ui.theme_button(st, "lp_theme_toggle", "☀ LIGHT", "☾ DARK")
    with right.container(key="lp_btn_nav"):
        st.page_link("views/home.py", label="OPEN DASHBOARD")

text, visual = st.columns([1, 1.3], gap="medium", vertical_alignment="center")
with text:
    st.markdown(
        "<div class='lp-eyebrow'><b>ZAMBIA</b> × <b>CHINA</b> TRADE INTELLIGENCE</div>"
        "<div class='lp-quote' role='heading' aria-level='1'>TRADE IS MORE THAN A TRANSACTION. IT IS A PATTERN WAITING TO BE UNDERSTOOD.</div>"
        "<div class='lp-rule'></div><div class='lp-sub'>Explore the connections behind Zambia–China trade.</div>",
        unsafe_allow_html=True,
    )
    with st.container(key="lp_btn_primary"):
        st.page_link("views/home.py", label="EXPLORE TRADE DATA →")
    active = c.datasets[(c.datasets["is_active"]) & (c.datasets["status"] == "complete")] if not c.datasets.empty else c.datasets
    if c.has_data and not active.empty:
        years = f"{int(active['year_min'].min())}–{int(active['year_max'].max())}"
        refreshed = pd.to_datetime(active["updated_at"]).max()
        flag = " · synthetic demonstration data" if c.synthetic else ""
        status = f"Data: UN Comtrade · {escape(', '.join(active['name'].astype(str)))} · {years} · updated {refreshed:%Y-%m-%d}{flag}"
    else:
        status = "No trade data imported yet. Add a dataset on the Data Management page."
    st.markdown(f"<div class='lp-status'>{status}</div>", unsafe_allow_html=True)
with visual:
    st.markdown(f"<div class='lp-world-wrap'>{world_img(theme)}"
                "<div class='lp-world-note'>Illustrative map. The line does not represent trade volume or a shipping route.</div></div>",
                unsafe_allow_html=True)
