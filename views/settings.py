import platform
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

import pandas as pd
import streamlit as st

from src import config, database, ui

c = ui.ctx()
ui.page_header("Settings & About", "Application preferences, database maintenance and project information.")
ui.show_flash()
engine = c.engine
s = database.get_settings(engine)

st.subheader("Preferences")
with st.form("settings"):
    a1, a2, a3 = st.columns(3)
    scale = a1.selectbox("Default display unit", list(ui.SCALES), index=list(ui.SCALES).index(s["display_scale"]))
    top_n = a2.selectbox("Default number of top products", [5, 10, 15, 20], index=[5, 10, 15, 20].index(int(s["top_n"])) if int(s["top_n"]) in (5, 10, 15, 20) else 1)
    interval = a3.selectbox("Default prediction interval", [80, 90, 95], index=[80, 90, 95].index(int(s["forecast_interval_level"])))
    b1, b2, b3, b4 = st.columns(4)
    min_train = b1.number_input("Forecast minimum training size (annual)", 3, 30, int(s["forecast_min_train"]))
    tol = b2.number_input("Parsimony tolerance %", 0.0, 50.0, float(s["parsimony_tolerance_pct"]), step=1.0)
    eps = b3.number_input("MAPE near-zero threshold (share of mean)", 0.0, 0.5, float(s["mape_epsilon_share"]), step=0.005, format="%.3f")
    vol = b4.number_input("Volatility warning threshold", 0.05, 5.0, float(s["volatility_warning_threshold"]), step=0.05)
    if st.form_submit_button("Save preferences", type="primary", disabled=config.read_only()):
        for k, v in {
            "display_scale": scale,
            "top_n": int(top_n),
            "forecast_interval_level": int(interval),
            "forecast_min_train": int(min_train),
            "parsimony_tolerance_pct": float(tol),
            "mape_epsilon_share": float(eps),
            "volatility_warning_threshold": float(vol),
        }.items():
            database.set_setting(engine, k, v)
        ui.flash("Preferences saved. They apply to new sessions and pages that use defaults.")
        st.rerun()
st.caption("Preferences are stored in the SQLite database and persist across restarts.")

st.subheader("Database")
db_file = database.database_file(engine)
size_mb = db_file.stat().st_size / 1e6 if db_file.exists() else 0
d1, d2, d3 = st.columns(3)
ui.kpi(d1, "Database file", db_file.name, help=str(db_file))
ui.kpi(d2, "Size", f"{size_mb:.2f} MB")
ui.kpi(d3, "Schema version", str(database.schema_version(engine)))
if st.button("Create backup copy", disabled=config.read_only()):
    dest = db_file.parent / "backups" / f"trade_intelligence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    database.backup_database(engine, dest)
    st.success(f"Backup written to {dest.relative_to(config.PROJECT_ROOT) if dest.is_relative_to(config.PROJECT_ROOT) else dest}")
    with open(dest, "rb") as fh:
        st.download_button("Download backup", fh.read(), dest.name, "application/octet-stream")
st.caption(
    "Backups use SQLite's online backup API, so they are consistent even while the app is running. To restore, stop the app and copy a backup over database/trade_intelligence.db."
)

st.subheader("UN Comtrade API")
st.write(
    "Subscription key configured"
    if config.comtrade_api_key()
    else "No key configured — the public preview endpoint is used (max 500 records). Add COMTRADE_API_KEY to .env to enable full downloads."
)
st.caption("The key is read from the environment only; it is never shown, logged or stored in the database.")

st.subheader("About")
st.markdown(f"**{config.APP_TITLE}** v{config.APP_VERSION}  \n{config.APP_SUBTITLE}")
st.markdown(
    "Undergraduate thesis project, Computer Science and Technology. The system answers three research questions:\n"
    "- **RQ1** How have Zambia's exports to China evolved, which products dominate, and how concentrated is the basket?\n"
    "- **RQ2** How do Zambia-reported exports compare with China-reported imports, and what explains the differences?\n"
    "- **RQ3** How accurately can statistical methods forecast copper export values?"
)
pkgs = ["streamlit", "pandas", "numpy", "plotly", "statsmodels", "scikit-learn", "SQLAlchemy", "pydantic", "openpyxl", "reportlab", "requests"]
rows = []
for p in pkgs:
    try:
        rows.append({"package": p, "version": version(p)})
    except PackageNotFoundError:
        rows.append({"package": p, "version": "not installed"})
with st.expander("Environment"):
    st.write(f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}")
    st.dataframe(pd.DataFrame(rows), hide_index=True)
