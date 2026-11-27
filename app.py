import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src import bootstrap, config, database, ui

st.set_page_config(page_title="Sino-African Trade Intelligence", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
try:
    for _key in ("TRADE_AUTOLOAD", "TRADE_READ_ONLY"):
        if _key not in os.environ and _key in st.secrets:
            os.environ[_key] = str(st.secrets[_key])
except Exception:
    pass
config.ensure_directories()
ui.inject_css()


@st.cache_resource(show_spinner=False)
def _autoload_once(db_file: str) -> list[dict]:
    engine = database.init_db(database.get_engine(db_file))
    return bootstrap.autoload(engine)


if config.autoload_enabled():
    with st.spinner("Preparing the demonstration data (first start only, about a minute)…"):
        _autoload_once(str(config.db_path()))

PAGES = {
    "Welcome": [
        st.Page("views/landing.py", title="Home", icon="🌍", default=True),
    ],
    "Analysis": [
        st.Page("views/home.py", title="Executive Overview", icon="📊"),
        st.Page("views/trade_explorer.py", title="Trade Explorer", icon="🔎"),
        st.Page("views/product_composition.py", title="Product Composition", icon="🧩"),
        st.Page("views/trade_mirror.py", title="Trade Mirror Analysis", icon="🪞"),
        st.Page("views/copper_forecasting.py", title="Copper Forecasting", icon="📈"),
        st.Page("views/trade_outlook.py", title="Trade Outlook (5–10 yrs)", icon="🔭"),
    ],
    "Data & Output": [
        st.Page("views/data_management.py", title="Data Management", icon="🗄️"),
        st.Page("views/reports.py", title="Reports & Exports", icon="📄"),
        st.Page("views/methodology.py", title="Methodology & Data Quality", icon="📐"),
        st.Page("views/settings.py", title="Settings & About", icon="⚙️"),
    ],
}

page = st.navigation(PAGES)
try:
    st.session_state["_ctx"] = ui.build_context()
except Exception as exc:
    config.get_logger().exception("Failed to build application context")
    st.error(f"The database could not be loaded: {exc}. See README › Troubleshooting › SQLite initialization failures.")
    st.stop()
page.run()
