from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from src import comtrade_client as ct
from src import config, database, ui
from src import data_ingestion as di
from src.data_cleaning import CLEANING_RULES
from src.data_validation import RULES
from src.schema import CANONICAL_FIELDS, CONSTANT_ALLOWED_FIELDS, COUNTRIES, REQUIRED_FIELDS, ComtradeQuery

c = ui.ctx()
ui.page_header("Data Management", "Upload, validate, import and audit trade datasets. Original files are never modified.")
ui.show_flash()
if c.synthetic:
    st.warning("Synthetic demonstration data is currently active. Deactivate it below before analysing real data.", icon="⚠️")
engine = c.engine
if config.read_only():
    st.info("This is the public read-only demonstration of the dashboard. Uploading, importing, deleting and API retrieval are switched off here; they work in the local installation.", icon="🔒")
    ds = database.list_datasets(engine)
    if not ds.empty:
        cols = [x for x in ("id", "name", "status", "is_active", "created_at") if x in ds.columns]
        st.dataframe(ds[cols], hide_index=True)
    st.caption("Source: UN Comtrade (United Nations Statistics Division), downloaded 2 November 2026.")
    st.stop()


def show_pipeline(result: dict, key: str) -> None:
    sm = result["summary"]
    k = st.columns(4)
    ui.kpi(k[0], "Rows read", f"{sm['raw_rows']:,}")
    ui.kpi(k[1], "Valid rows", f"{sm['clean_rows']:,}")
    ui.kpi(k[2], "Excluded rows", f"{sm['excluded_rows']:,}")
    ui.kpi(k[3], "Years", f"{sm['year_min']}–{sm['year_max']}" if sm["year_min"] else "n/a")
    st.caption(
        f"Perspective: {sm.get('perspective') or 'n/a'} · HS levels: {sm.get('hs_levels')} · Classifications: {sm.get('classifications')} · "
        f"Currencies: {sm.get('currencies')} · Frequency: {sm.get('frequency')}"
    )
    for chk in sm.get("dataset_checks", []):
        (st.warning if chk["severity"] == "warning" else st.info)(f"**{chk['check']}** — {chk['message']}")
    if sm.get("rule_counts"):
        st.markdown("**Validation rules triggered**")
        st.dataframe(pd.DataFrame(sm["rule_counts"]), hide_index=True)
    issues = result["issues"]
    if not issues.empty:
        with st.expander(f"Row-level issues ({len(issues):,})", expanded=sm["excluded_rows"] > 0):
            sev = st.multiselect("Severity", ["error", "warning", "info"], default=["error", "warning"], key=f"{key}_sev")
            st.dataframe(issues[issues["severity"].isin(sev)], hide_index=True, height=300)
            st.download_button("Download issue report (CSV)", issues.to_csv(index=False).encode("utf-8-sig"), "validation_issues.csv", "text/csv", key=f"{key}_iss")
            st.caption("Row numbers count data rows from 1 (the header is not counted).")
    st.markdown("**Cleaned preview (first 100 rows)**")
    preview_cols = [
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
        "quantity_unit",
        "valuation_basis",
        "quality_flags",
    ]
    st.dataframe(result["clean"][preview_cols].head(100), hide_index=True, height=260)


def upload_flow(up) -> None:
    content = up.getvalue()
    digest = di.file_hash(content)
    fk = digest[:10]
    try:
        sheet = None
        if up.name.lower().endswith((".xlsx", ".xlsm")):
            sheets = di.excel_sheets(content)
            sheet = st.selectbox("Worksheet", sheets, key=f"sheet_{fk}") if len(sheets) > 1 else sheets[0]
        raw, info = di.read_table(up.name, content, sheet)
    except di.IngestionError as exc:
        st.error(str(exc))
        return
    dup = database.find_dataset_by_hash(engine, digest)
    if dup and dup["status"] == "complete":
        st.warning(f"This exact file was already imported as dataset #{dup['id']} ('{dup['name']}'). Importing again is blocked to prevent double counting.")
    st.markdown(
        f"**{info['file_name']}** · {info['rows']:,} rows · {len(info['columns'])} columns"
        + (f" · encoding {info.get('encoding')} · delimiter '{info.get('delimiter')}'" if info.get("encoding") else "")
    )
    if di.is_comtrade_layout(raw.columns):
        st.success("Recognised UN Comtrade column layout; mapping suggested automatically. Please review it.")
    p1, p2 = st.tabs(["Preview", "Columns & types"])
    p1.dataframe(raw.head(50), hide_index=True, height=260)
    p2.dataframe(di.column_profile(raw), hide_index=True)
    st.markdown("#### Column mapping")
    st.caption(
        "Map source columns to the canonical schema. Required: year (or period) and trade value. Reporter, partner and flow need a column "
        "or a constant. Unmapped optional fields stay empty."
    )
    sugg = di.suggest_mapping(raw.columns)
    cols = [""] + list(raw.columns)
    mapping_cols = {}
    order = list(REQUIRED_FIELDS) + [
        "reporter_code",
        "reporter_name",
        "partner_code",
        "partner_name",
        "flow",
        "hs_code",
        "product_description",
        "classification",
        "period",
        "month",
        "frequency",
        "currency",
        "net_weight_kg",
        "quantity",
        "quantity_unit",
        "valuation_basis",
        "data_source",
        "original_record_id",
        "aggregate_level",
        "mot_code",
        "customs_code",
        "partner2_code",
        "cif_value",
        "fob_value",
    ]
    grid = st.columns(3)
    for i, f in enumerate(order):
        default = sugg["columns"].get(f, "")
        val = grid[i % 3].selectbox(
            f"{f}{' *' if f in REQUIRED_FIELDS else ''}", cols, index=cols.index(default) if default in cols else 0, key=f"map_{fk}_{f}", help=CANONICAL_FIELDS[f]
        )
        if val:
            mapping_cols[f] = val
    st.markdown("**Constants for fields missing from the file**")
    cgrid = st.columns(4)
    constants = {}
    for i, f in enumerate(CONSTANT_ALLOWED_FIELDS):
        v = cgrid[i % 4].text_input(
            f,
            value=sugg["constants"].get(f, ""),
            key=f"const_{fk}_{f}",
            help=f"{CANONICAL_FIELDS[f]}. Used only when no column is mapped. Countries: M49 code, ISO3 or name; flow: X/M/RX/RM.",
        )
        if v.strip():
            constants[f] = v.strip()
    mapping = {"columns": mapping_cols, "constants": constants}
    try:
        di.validate_mapping(mapping)
        mapping_ok = True
    except ValidationError as exc:
        mapping_ok = False
        st.error("Mapping incomplete: " + "; ".join(e["msg"].replace("Value error, ", "") for e in exc.errors()))
    if mapping_ok:
        st.markdown("#### Validation")
        result = di.preview_pipeline(raw, mapping, constants.get("data_source", "User upload"))
        show_pipeline(result, f"pv_{fk}")
        ov = di.overlap_report(engine, result["clean"])
        if not ov.empty:
            st.warning(
                "Some records already exist in other datasets (same reporter, partner, flow, period and code). When both datasets are "
                "active, only the most recently imported copy is used, so values are not double counted."
            )
            st.dataframe(ov, hide_index=True)
        st.markdown("#### Import")
        i1, i2 = st.columns([2, 1])
        name = i1.text_input("Dataset name", value=up.name.rsplit(".", 1)[0], key=f"name_{fk}")
        synthetic = i2.checkbox(
            "Synthetic / demonstration data", value="synthetic" in up.name.lower(), key=f"syn_{fk}", help="Synthetic datasets are labelled on every page and in every report."
        )
        notes = st.text_area("Notes (provenance, download date, query used)", key=f"notes_{fk}", height=70)
        disabled = result["summary"]["clean_rows"] == 0 or (dup is not None and dup["status"] == "complete")
        if st.button("Import valid records into the database", type="primary", disabled=disabled, key=f"imp_{fk}"):
            with st.spinner("Importing…"):
                out = di.import_table(engine, raw, mapping, dataset_name=name or up.name, file_name=up.name, content=content, is_synthetic=synthetic, notes=notes or None)
            ui.refresh_data()
            ui.flash(out["message"], "success" if out["status"] == "imported" else "warning")
            st.rerun()


tab_up, tab_ds, tab_api, tab_raw, tab_log, tab_rules = st.tabs(["Upload & import", "Datasets", "UN Comtrade API", "Raw vs. cleaned", "Import history", "Cleaning rules"])

with tab_up:
    candidates = [p for p in (config.RAW_DIR / config.PRIMARY_DATASET_NAME, config.PROJECT_ROOT / config.PRIMARY_DATASET_NAME) if p.exists()]
    known = set(c.datasets["file_name"]) if not c.datasets.empty else set()
    for p in candidates:
        if p.name not in known:
            st.info(f"Found **{p.relative_to(config.PROJECT_ROOT)}** in the project folder. It has not been imported yet.")
            if st.button(f"Import {p.name} with automatic Comtrade mapping", key=f"prim_{p}"):
                try:
                    out = di.import_file(engine, p)
                    ui.refresh_data()
                    ui.flash(out["message"], "success" if out["status"] == "imported" else "warning")
                    st.rerun()
                except di.IngestionError as exc:
                    st.error(str(exc))
            break
    up = st.file_uploader(f"Upload a CSV or Excel file (max {config.MAX_UPLOAD_MB} MB)", type=["csv", "txt", "xlsx", "xlsm"], key="dm_upload")
    if up is not None:
        upload_flow(up)

with tab_ds:
    ds = database.list_datasets(engine)
    if ds.empty:
        st.info("No datasets imported yet.")
    else:
        view = ds[
            [
                "id",
                "name",
                "file_name",
                "source_label",
                "is_synthetic",
                "is_active",
                "status",
                "frequency",
                "year_min",
                "year_max",
                "row_count_raw",
                "row_count_clean",
                "row_count_excluded",
                "perspective",
                "pipeline_version",
                "imported_at",
                "updated_at",
            ]
        ]
        st.dataframe(view, hide_index=True, column_config={"is_synthetic": st.column_config.CheckboxColumn("Synthetic"), "is_active": st.column_config.CheckboxColumn("Active")})
        sel = st.selectbox("Select dataset", list(ds["id"]), format_func=lambda i: f"#{i} – {ds.set_index('id').loc[i, 'name']}", key="ds_sel")
        row = ds.set_index("id").loc[sel]
        a1, a2, a3, a4 = st.columns(4)
        if row["is_active"]:
            if a1.button("Deactivate", width="stretch", help="Exclude from all analyses without deleting"):
                database.set_dataset_active(engine, int(sel), False)
                ui.refresh_data()
                st.rerun()
        elif a1.button("Activate", width="stretch"):
            database.set_dataset_active(engine, int(sel), True)
            ui.refresh_data()
            st.rerun()
        if a2.button("Reprocess from raw records", width="stretch", help="Re-run the documented cleaning pipeline on the stored raw rows"):
            try:
                res = di.reprocess_dataset(engine, int(sel))
                ui.refresh_data()
                st.success(f"Reprocessed: {res['summary']['clean_rows']:,} valid rows, {res['summary']['excluded_rows']:,} excluded.")
            except di.IngestionError as exc:
                st.error(str(exc))
        clean = di.clean_export(engine, int(sel))
        a3.download_button("Download cleaned CSV", clean.to_csv(index=False).encode("utf-8-sig"), f"dataset_{sel}_clean.csv", "text/csv", width="stretch")
        if a4.button("Save to data/processed", width="stretch"):
            out = di.write_processed(engine, int(sel))
            st.success(f"Written to {out.relative_to(config.PROJECT_ROOT)}")
        with st.expander("Cleaning summary and column mapping"):
            st.json(
                {
                    "cleaning_summary": row["cleaning_summary"],
                    "column_mapping": row["column_mapping"],
                    "stored_copy": row["stored_copy"],
                    "notes": row["notes"],
                    "retrieved_at": str(row["retrieved_at"]) if pd.notna(row["retrieved_at"]) else None,
                }
            )
        with st.expander("Delete dataset"):
            st.caption("Removes the dataset's records from the database. The original file and the stored upload copy are kept on disk.")
            confirm = st.checkbox(f"I understand dataset #{sel} will be removed from the database", key=f"del_ok_{sel}")
            if st.button("Delete dataset", disabled=not confirm, key=f"del_{sel}"):
                database.delete_dataset(engine, int(sel))
                ui.refresh_data()
                st.rerun()
    st.divider()
    st.markdown("**Demonstration data**")
    st.caption("A clearly labelled SYNTHETIC Zambia–China mirror dataset (both reporters, 2015–2024) for testing the workflows. It is not real data.")
    if st.button("Import synthetic demo dataset"):
        if not config.SYNTHETIC_SAMPLE_FILE.exists():
            from scripts.generate_synthetic_demo import generate

            generate().to_csv(config.SYNTHETIC_SAMPLE_FILE, index=False)
        out = di.import_file(engine, config.SYNTHETIC_SAMPLE_FILE, dataset_name="SYNTHETIC demo – Zambia/China mirror", is_synthetic=True)
        ui.refresh_data()
        ui.flash(out["message"], "success" if out["status"] == "imported" else "warning")
        st.rerun()

with tab_api:
    key_set = config.comtrade_api_key() is not None
    st.markdown(
        "Retrieve official statistics from the UN Comtrade API. "
        + (
            "A subscription key is configured (from `.env`)."
            if key_set
            else "No subscription key configured: the public **preview** endpoint is used (max 500 records per request). Add `COMTRADE_API_KEY` to `.env` for full access."
        )
    )
    country_opts = list(COUNTRIES)
    with st.form("api_form"):
        f1, f2, f3, f4 = st.columns(4)
        rep = f1.selectbox("Reporter", country_opts, index=country_opts.index("894"), format_func=lambda x: f"{COUNTRIES[x][0]} ({x})")
        par = f2.selectbox("Partner", country_opts, index=country_opts.index("156"), format_func=lambda x: f"{COUNTRIES[x][0]} ({x})")
        flow = f3.selectbox("Flow", ["X", "M", "RX", "RM"], format_func=lambda x: {"X": "Export", "M": "Import", "RX": "Re-export", "RM": "Re-import"}[x])
        freq = f4.selectbox("Frequency", ["A", "M"], format_func=lambda x: {"A": "Annual", "M": "Monthly"}[x])
        g1, g2, g3 = st.columns([2, 2, 1])
        yrs = g1.slider("Years", 2000, date.today().year - 1, (2015, min(2024, date.today().year - 1)))
        cmd = g2.text_input(
            "Commodity codes (comma-separated)",
            "TOTAL,260300,740311,740200",
            help="HS codes (2/4/6 digits), TOTAL, or AG2/AG4/AG6 for all codes at that level (large; needs a subscription key).",
        )
        cls = g3.selectbox("Classification", ["HS", "H6", "H5", "H4"])
        use_cache = st.checkbox("Use cached response if available", value=True)
        submitted = st.form_submit_button("Fetch from UN Comtrade")
    if submitted:
        try:
            periods = list(range(yrs[0], yrs[1] + 1))
            if freq == "M":
                periods = [int(f"{yrs[1]}{m:02d}") for m in range(1, 13)]
                st.caption(f"Monthly requests fetch the 12 months of {yrs[1]} per call.")
            q = ComtradeQuery(
                freq_code=freq, classification=cls, reporter_code=rep, partner_code=par, flow_code=flow, periods=periods, cmd_codes=[x for x in cmd.split(",") if x.strip()]
            )
            with st.spinner("Contacting UN Comtrade…"):
                payload = ct.fetch(q, use_cache=use_cache)
            st.session_state["api_payload"] = payload
        except ValidationError as exc:
            st.error("Invalid request: " + "; ".join(e["msg"].replace("Value error, ", "") for e in exc.errors()))
        except ct.ComtradeError as exc:
            st.error(str(exc))
    payload = st.session_state.get("api_payload")
    if payload:
        try:
            frame = ct.to_frame(payload)
        except ct.ComtradeError as exc:
            st.error(str(exc))
            frame = pd.DataFrame()
        st.markdown(f"Retrieved **{len(frame):,}** records at {payload['retrieved_at']} {'(from cache)' if payload.get('from_cache') else ''} · endpoint `{payload['endpoint']}`")
        if payload.get("truncated"):
            st.warning("The preview endpoint returned its maximum of 500 records, so the result may be incomplete. Narrow the query or use a subscription key.")
        if frame.empty:
            st.info("No records returned for this query.")
        else:
            st.dataframe(frame.head(200), hide_index=True, height=260)
            mapping = di.suggest_mapping(frame.columns)
            mapping["constants"]["data_source"] = "UN Comtrade API"
            res = di.preview_pipeline(frame, mapping, "UN Comtrade API")
            show_pipeline(res, "api")
            nm = st.text_input(
                "Dataset name", f"Comtrade API {payload['params']['reporterCode']}-{payload['params']['partnerCode']} {payload['params']['flowCode']} {payload['params']['period']}"
            )
            if st.button("Import API records", type="primary"):
                out = di.import_table(
                    engine,
                    frame,
                    mapping,
                    dataset_name=nm,
                    file_name="comtrade_api.json",
                    content=ct.payload_bytes(payload),
                    source_label="UN Comtrade API",
                    notes=f"Query: {payload['params']}",
                    retrieved_at=datetime.fromisoformat(payload["retrieved_at"]).astimezone(timezone.utc).replace(tzinfo=None),
                )
                ui.refresh_data()
                ui.flash(out["message"], "success" if out["status"] == "imported" else "warning")
                st.rerun()

with tab_raw:
    ds = database.list_datasets(engine)
    if ds.empty:
        st.info("No datasets imported yet.")
    else:
        sel = st.selectbox("Dataset", list(ds["id"]), format_func=lambda i: f"#{i} – {ds.set_index('id').loc[i, 'name']}", key="raw_sel")
        raw_rows = database.load_raw_records(engine, int(sel))
        st.markdown(f"**Raw records as uploaded** ({len(raw_rows):,} rows, stored unchanged)")
        st.dataframe(pd.DataFrame(raw_rows[:500]), hide_index=True, height=260)
        st.markdown("**Normalised analytical records**")
        st.dataframe(di.clean_export(engine, int(sel)).head(500), hide_index=True, height=260)

with tab_log:
    logs = database.import_logs(engine)
    st.dataframe(logs, hide_index=True, height=420)

with tab_rules:
    st.markdown("**Cleaning pipeline (version " + config.PIPELINE_VERSION + ")**")
    st.dataframe(pd.DataFrame(CLEANING_RULES, columns=["id", "step", "rule"]), hide_index=True)
    st.markdown("**Validation rules**")
    st.dataframe(pd.DataFrame([(k, *v) for k, v in RULES.items()], columns=["rule", "check", "severity", "action"]), hide_index=True)
