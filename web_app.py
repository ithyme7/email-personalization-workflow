from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from cli import run
from config import DATA_DIR, OUTPUT_DIR, load_settings
from cost_estimator import CostEstimate, estimate_batch_cost, price_for_model
from export import CLIENT_REVIEW_COLUMNS, _client_rows
from google_sheets import (
    GoogleSheetsError,
    dataframe_to_temp_csv,
    export_dataframe_to_sheet,
    read_private_sheet,
    read_public_sheet,
)
from tone_preset_library import get_preset_profile, preset_options
from tone_profiles import available_tone_profiles, load_tone_profile


DEFAULT_CONTEXT = "We help mobile app teams with this type of work, figure out where users drop off and why."
RUN_INPUT_DIR = DATA_DIR / "ui_uploads"
RUN_OUTPUT_DIR = OUTPUT_DIR / "ui_runs"
CUSTOM_PROFILE_DIR = DATA_DIR / "custom_tone_profiles"


st.set_page_config(
    page_title="Email Personalization Workflow",
    page_icon="*",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.35rem; padding-bottom: 2rem; }
        div[data-testid="stMetric"] {
            background: #111827;
            border: 1px solid #334155;
            padding: 15px 16px;
            border-radius: 8px;
        }
        .ux-card {
            border: 1px solid #334155;
            background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
            border-radius: 8px;
            padding: 18px;
            min-height: 116px;
        }
        .ux-card strong { color: #F8FAFC; }
        .ux-muted { color: #CBD5E1; font-size: 0.92rem; }
        .ux-badge {
            display: inline-block;
            border: 1px solid #334155;
            border-radius: 999px;
            padding: 4px 10px;
            color: #E2E8F0;
            margin: 0 6px 8px 0;
            font-size: 0.78rem;
        }
        .ux-good { color: #22C55E; font-weight: 700; }
        .ux-warn { color: #FB923C; font-weight: 700; }
        .ux-bad { color: #F87171; font-weight: 700; }
        .stButton > button { border-radius: 8px; font-weight: 700; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _safe_name(value: str) -> str:
    allowed = [char.lower() if char.isalnum() else "_" for char in value.strip()]
    return "_".join("".join(allowed).split("_")) or "custom_profile"


def _write_uploaded_csv(uploaded_file) -> Path:
    RUN_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = _safe_name(Path(uploaded_file.name).stem)
    path = RUN_INPUT_DIR / f"{filename}_{stamp}.csv"
    path.write_bytes(uploaded_file.getvalue())
    return path


def _write_service_account(uploaded_file) -> Path:
    RUN_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RUN_INPUT_DIR / f"google_service_account_{stamp}.json"
    path.write_bytes(uploaded_file.getvalue())
    return path


def _output_path(input_path: Path) -> Path:
    RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return RUN_OUTPUT_DIR / f"{input_path.stem}_review_{stamp}.xlsx"


def _profile_description(name: str) -> str:
    profile = get_preset_profile(name)
    if profile:
        return profile.description
    return load_tone_profile(name).description or "Custom tone profile."


def _custom_profile_path(
    preset_name: str,
    custom_name: str,
    custom_prompt: str,
    good_examples: str,
    bad_examples: str,
) -> Path:
    CUSTOM_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    base = get_preset_profile(preset_name) or load_tone_profile(preset_name)
    name = _safe_name(custom_name or f"custom_{preset_name}")
    payload = base.to_prompt_payload()
    payload["name"] = name
    payload["description"] = f"Client-specific profile based on {preset_name}."
    payload["custom_prompt"] = custom_prompt.strip()
    if good_examples.strip():
        payload["example_good_lines"] = [line.strip() for line in good_examples.splitlines() if line.strip()]
    if bad_examples.strip():
        payload["example_bad_lines"] = [line.strip() for line in bad_examples.splitlines() if line.strip()]
    path = CUSTOM_PROFILE_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _rows_to_review_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    review_rows, _ = _client_rows(rows)
    df = pd.DataFrame(review_rows, columns=CLIENT_REVIEW_COLUMNS)
    ordered = [
        "status",
        "company",
        "person",
        "role",
        "website",
        "personalized_line",
        "template_preview",
        "evidence_found",
        "quality_flags",
        "needs_manual_review",
        "reviewer_notes",
        "friction_type",
        "surface_checked",
        "conversion_outcome",
        "visual_confidence",
        "visual_confidence_score",
        "visual_confidence_reasons",
        "visual_flags",
        "screenshots",
        "source_urls",
    ]
    return df[[col for col in ordered if col in df.columns]]


def _df_to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Review")
        worksheet = writer.book["Review"]
        widths = {
            "A": 14,
            "B": 24,
            "C": 22,
            "D": 24,
            "E": 34,
            "F": 76,
            "G": 84,
            "H": 84,
            "I": 32,
            "J": 18,
            "K": 68,
            "L": 24,
            "M": 24,
            "N": 24,
            "O": 18,
            "P": 18,
        }
        for col, width in widths.items():
            worksheet.column_dimensions[col].width = width
        for row in worksheet.iter_rows():
            for cell in row:
                cell.alignment = cell.alignment.copy(wrap_text=True, vertical="top")
    return buffer.getvalue()


def _make_args(input_path: Path, output_path: Path, campaign_context: str, tone_profile: str) -> argparse.Namespace:
    return argparse.Namespace(
        input=str(input_path),
        output=str(output_path),
        campaign_context=campaign_context,
        manual_review_mode=True,
        reuse_duplicate_personalization=True,
        client_batch_output=True,
        deep_research=True,
        tone_profile=tone_profile,
        log_level="INFO",
    )


def _set_api_env(provider: str, api_key: str, model_name: str) -> None:
    os.environ["LLM_PROVIDER"] = provider
    os.environ["MODEL_NAME"] = model_name
    if api_key.strip():
        key_by_provider = {
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        os.environ[key_by_provider[provider]] = api_key.strip()


def _sidebar_settings() -> tuple[str, str, str, float, float]:
    settings = load_settings()
    st.sidebar.header("Model")
    providers = ["gemini", "openrouter", "deepseek", "openai"]
    provider = st.sidebar.selectbox("Provider", providers, index=providers.index(settings.llm_provider))
    model_name = st.sidebar.text_input("Model name", settings.model_name)
    api_key = st.sidebar.text_input("API key for this run", type="password")
    st.sidebar.caption("Laat leeg voor research-only output. Keys worden niet in de code opgeslagen.")

    st.sidebar.header("Cost estimate")
    default_input_price, default_output_price = price_for_model(model_name)
    input_price = st.sidebar.number_input(
        "Input price per 1M tokens",
        min_value=0.0,
        value=float(default_input_price),
        step=0.01,
        format="%.4f",
    )
    output_price = st.sidebar.number_input(
        "Output price per 1M tokens",
        min_value=0.0,
        value=float(default_output_price),
        step=0.01,
        format="%.4f",
    )
    st.sidebar.caption("Editable estimate. Check actual provider pricing before quoting margin.")
    return provider, model_name, api_key, input_price, output_price


def _load_google_sheet_to_csv(sheet_url: str, worksheet_name: str, service_account_file) -> Path:
    credential_path: Path | None = None
    try:
        if service_account_file is not None:
            credential_path = _write_service_account(service_account_file)
            df = read_private_sheet(sheet_url, str(credential_path), worksheet_name)
        else:
            df = read_public_sheet(sheet_url, worksheet_name)
        if df.empty:
            raise GoogleSheetsError("The Google Sheet loaded, but it did not contain rows.")
        return dataframe_to_temp_csv(df, RUN_INPUT_DIR)
    finally:
        if credential_path and credential_path.exists():
            credential_path.unlink(missing_ok=True)


def _progress_callback(progress_bar, status_box):
    def update(payload: dict[str, Any]) -> None:
        progress = max(0.0, min(1.0, float(payload.get("progress", 0.0))))
        current = payload.get("current", 0)
        total = payload.get("total", 0)
        stage = payload.get("stage", "Running")
        company = payload.get("company", "")
        suffix = f" - {company}" if company else ""
        progress_bar.progress(progress, text=f"{stage}: {current}/{total}{suffix}")
        status_box.write(f"{stage}: {current}/{total}{suffix}")

    return update


def _run_batch(
    input_path: Path,
    campaign_context: str,
    tone_profile: str,
    provider: str,
    model_name: str,
    api_key: str,
    input_price: float,
    output_price: float,
) -> tuple[list[dict[str, Any]], Path]:
    _set_api_env(provider, api_key, model_name)
    output_path = _output_path(input_path)
    progress_bar = st.progress(0, text="Preparing batch...")
    status_box = st.empty()
    rows = run(
        _make_args(input_path, output_path, campaign_context, tone_profile),
        progress_callback=_progress_callback(progress_bar, status_box),
    )
    progress_bar.progress(1.0, text="Complete")
    cost = estimate_batch_cost(rows, input_price, output_price)
    for row in rows:
        row["estimated_model_cost_usd"] = round(cost.estimated_cost_usd, 6)
    st.session_state["rows"] = rows
    st.session_state["review_df"] = _rows_to_review_df(rows)
    st.session_state["output_path"] = str(output_path)
    st.session_state["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.session_state["cost_estimate"] = cost
    return rows, output_path


def _count_status(df: pd.DataFrame, status: str) -> int:
    return int((df["status"] == status).sum()) if "status" in df else 0


def _top_split_counts(df: pd.DataFrame, column: str, limit: int = 10) -> pd.DataFrame:
    counts: dict[str, int] = {}
    if column not in df:
        return pd.DataFrame(columns=["label", "rows"])
    for value in df[column].fillna("").astype(str):
        for item in value.replace("\n", "|").replace(";", "|").split("|"):
            item = item.strip()
            if item:
                counts[item] = counts.get(item, 0) + 1
    rows = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    return pd.DataFrame(rows, columns=["label", "rows"])


def _dashboard(df: pd.DataFrame, cost: CostEstimate | None) -> None:
    total = len(df)
    unique_companies = df["company"].nunique() if "company" in df else 0
    ready = _count_status(df, "Ready")
    review = _count_status(df, "Review")
    research_only = _count_status(df, "Research only")
    generated = int((df["personalized_line"].fillna("").astype(str).str.len() > 0).sum()) if "personalized_line" in df else 0

    st.subheader("Batch dashboard")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", total, f"{unique_companies} unique companies")
    c2.metric("Ready", ready, f"{round(ready / total * 100) if total else 0}%")
    c3.metric("Needs review", review)
    c4.metric("Research only", research_only)
    c5.metric("Generated", generated)

    if cost:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("LLM calls", cost.llm_calls)
        k2.metric("Input tokens", f"{cost.input_tokens:,}")
        k3.metric("Output tokens", f"{cost.output_tokens:,}")
        k4.metric("Est. model cost", f"${cost.estimated_cost_usd:.4f}", f"${cost.cost_per_row_usd:.5f}/row")

    left, right = st.columns(2, gap="large")
    with left:
        status_counts = df["status"].value_counts().rename_axis("status").reset_index(name="rows") if "status" in df else pd.DataFrame()
        if not status_counts.empty:
            st.markdown("**Status distribution**")
            st.bar_chart(status_counts.set_index("status"))

        flags = _top_split_counts(df, "quality_flags", 8)
        if not flags.empty:
            st.markdown("**Top quality flags**")
            st.bar_chart(flags.set_index("label"))

    with right:
        visual_counts = (
            df["visual_confidence"].fillna("none").replace("", "none").value_counts().rename_axis("visual_confidence").reset_index(name="rows")
            if "visual_confidence" in df
            else pd.DataFrame()
        )
        if not visual_counts.empty:
            st.markdown("**Visual bug confidence**")
            st.bar_chart(visual_counts.set_index("visual_confidence"))

        friction_counts = df["friction_type"].replace("", pd.NA).dropna().value_counts().rename_axis("friction_type").reset_index(name="rows") if "friction_type" in df else pd.DataFrame()
        if not friction_counts.empty:
            st.markdown("**Friction types found**")
            st.bar_chart(friction_counts.head(8).set_index("friction_type"))

    review_cols = [col for col in ["company", "person", "personalized_line", "quality_flags", "visual_confidence", "reviewer_notes"] if col in df]
    st.markdown("**Review queue**")
    if review_cols:
        queue = df[df["status"].isin(["Review", "Research only"])] if "status" in df else df
        st.dataframe(queue[review_cols], use_container_width=True, height=300)


def _profile_picker() -> str:
    tone_names = available_tone_profiles()
    default_index = tone_names.index("friction_first") if "friction_first" in tone_names else 0
    selected_tone = st.selectbox("Tone profile", tone_names, index=default_index)
    st.info(_profile_description(selected_tone))

    with st.expander("Optional: client-specific tone profile"):
        use_client_profile = st.checkbox("Use/create a client-specific profile")
        client_name = st.text_input("Client/profile name", value=f"client_{selected_tone}")
        custom_prompt = st.text_area(
            "Client-specific prompt",
            placeholder="Example: Start conversationally with 'I was checking out...', only use current friction, avoid broad strategy suggestions.",
            height=140,
        )
        good_examples = st.text_area("Good example lines, one per line", height=100)
        bad_examples = st.text_area("Bad example lines, one per line", height=100)

    if use_client_profile:
        return str(_custom_profile_path(selected_tone, client_name, custom_prompt, good_examples, bad_examples))
    return selected_tone


def main() -> None:
    _inject_css()
    st.title("Email Personalization Workflow")
    st.caption("Upload leads, choose context and tone, run the batch, review rows, then export.")

    provider, model_name, api_key, input_price, output_price = _sidebar_settings()

    dashboard_tab, setup_tab, review_tab, export_tab, presets_tab = st.tabs(
        ["Dashboard", "Setup & Run", "Review & Edit", "Export", "Tone Presets"]
    )

    with dashboard_tab:
        if "review_df" not in st.session_state:
            st.markdown(
                """
                <div class="ux-card">
                    <strong>No batch loaded yet.</strong>
                    <p class="ux-muted">Go to Setup & Run, upload a CSV or load a Google Sheet, then run the batch.</p>
                    <span class="ux-badge">CSV</span>
                    <span class="ux-badge">Google Sheets</span>
                    <span class="ux-badge">50 presets</span>
                    <span class="ux-badge">Custom client profiles</span>
                    <span class="ux-badge">Cost estimate</span>
                    <span class="ux-badge">Visual confidence</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            _dashboard(st.session_state["review_df"], st.session_state.get("cost_estimate"))

    with setup_tab:
        left, right = st.columns([1.05, 0.95], gap="large")
        with left:
            st.subheader("1. Input")
            input_source = st.radio("Lead source", ["CSV upload", "Google Sheets"], horizontal=True)
            input_path: Path | None = None
            uploaded_file = None
            sheet_url = ""
            worksheet_name = ""
            sheet_service_file = None

            if input_source == "CSV upload":
                uploaded_file = st.file_uploader("Lead CSV", type=["csv"])
            else:
                sheet_url = st.text_input("Google Sheets URL")
                worksheet_name = st.text_input("Worksheet name or tab name, optional")
                sheet_service_file = st.file_uploader("Service-account JSON, optional for private Sheets", type=["json"])
                st.caption("Public Sheets can be read without a JSON file. Private Sheets need service-account access.")
                if st.button("Preview Google Sheet", disabled=not sheet_url.strip()):
                    try:
                        preview_path = _load_google_sheet_to_csv(sheet_url, worksheet_name, sheet_service_file)
                        preview_df = pd.read_csv(preview_path, dtype=str).fillna("")
                        st.dataframe(preview_df.head(10), use_container_width=True)
                    except GoogleSheetsError as exc:
                        st.error(str(exc))

            st.subheader("2. Campaign context")
            campaign_context = st.text_area(
                "Sentence after the personalized line",
                value=DEFAULT_CONTEXT,
                height=95,
            )

            st.subheader("3. Tone")
            tone_for_run = _profile_picker()

            if st.button("Run batch", type="primary", use_container_width=True):
                try:
                    if input_source == "CSV upload":
                        if uploaded_file is None:
                            st.error("Upload a CSV first.")
                            st.stop()
                        input_path = _write_uploaded_csv(uploaded_file)
                    else:
                        if not sheet_url.strip():
                            st.error("Paste a Google Sheets URL first.")
                            st.stop()
                        input_path = _load_google_sheet_to_csv(sheet_url, worksheet_name, sheet_service_file)
                    rows, output_path = _run_batch(
                        input_path,
                        campaign_context,
                        tone_for_run,
                        provider,
                        model_name,
                        api_key,
                        input_price,
                        output_price,
                    )
                    st.success(f"Batch ready: {len(rows)} rows. Output saved to {output_path}")
                except Exception as exc:
                    st.error(str(exc))

        with right:
            st.subheader("Workflow")
            st.markdown(
                """
                <div class="ux-card">
                    <span class="ux-badge">1 Input</span>
                    <span class="ux-badge">2 Website/app research</span>
                    <span class="ux-badge">3 Evidence gate</span>
                    <span class="ux-badge">4 Tone profile</span>
                    <span class="ux-badge">5 Copy</span>
                    <span class="ux-badge">6 QC</span>
                    <span class="ux-badge">7 Review</span>
                    <span class="ux-badge">8 Export</span>
                    <p class="ux-muted" style="margin-top:12px;">
                    Weak evidence remains visible. Visual bug confidence and review flags help decide what needs manual checking.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if "review_df" in st.session_state:
                _dashboard(st.session_state["review_df"], st.session_state.get("cost_estimate"))

    with review_tab:
        if "review_df" not in st.session_state:
            st.info("Run a batch first. The editable review table will appear here.")
        else:
            st.subheader("Review and edit rows")
            df = st.session_state["review_df"].copy()
            filters = df["status"].dropna().unique().tolist() if "status" in df else []
            status_filter = st.multiselect("Filter status", sorted(filters), default=sorted(filters))
            filtered = df[df["status"].isin(status_filter)] if status_filter and "status" in df else df
            edited = st.data_editor(
                filtered,
                use_container_width=True,
                height=650,
                num_rows="fixed",
                column_config={
                    "personalized_line": st.column_config.TextColumn("personalized_line", width="large"),
                    "template_preview": st.column_config.TextColumn("template_preview", width="large"),
                    "evidence_found": st.column_config.TextColumn("evidence_found", width="large"),
                    "reviewer_notes": st.column_config.TextColumn("reviewer_notes", width="large"),
                    "needs_manual_review": st.column_config.SelectboxColumn("needs_manual_review", options=["yes", "no"]),
                    "status": st.column_config.SelectboxColumn("status", options=["Ready", "Review", "Research only"]),
                    "visual_confidence": st.column_config.SelectboxColumn("visual_confidence", options=["high", "medium", "low", "none", ""]),
                },
            )
            if st.button("Save visible edits", use_container_width=True):
                updated = df.copy()
                updated.loc[edited.index, edited.columns] = edited
                st.session_state["review_df"] = updated
                st.success("Edits saved in this session.")

    with export_tab:
        if "review_df" not in st.session_state:
            st.info("Run and review a batch first.")
        else:
            st.subheader("Export")
            df = st.session_state["review_df"]
            csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            xlsx_bytes = _df_to_xlsx_bytes(df)
            col1, col2, col3 = st.columns(3)
            col1.download_button("Download edited CSV", csv_bytes, "personalization_review_edited.csv", "text/csv", use_container_width=True)
            col2.download_button(
                "Download edited XLSX",
                xlsx_bytes,
                "personalization_review_edited.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            output_path = st.session_state.get("output_path")
            if output_path and Path(output_path).exists():
                col3.download_button(
                    "Download full workbook",
                    Path(output_path).read_bytes(),
                    Path(output_path).name,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

            with st.expander("Optional: export edited rows to Google Sheets"):
                export_url = st.text_input("Destination Google Sheets URL")
                export_tab_name = st.text_input("Destination worksheet name", value="Review")
                export_creds = st.file_uploader("Service-account JSON for export", type=["json"], key="export_creds")
                if st.button("Push to Google Sheets", disabled=not export_url.strip() or export_creds is None):
                    credential_path: Path | None = None
                    try:
                        credential_path = _write_service_account(export_creds)
                        export_dataframe_to_sheet(df, export_url, str(credential_path), export_tab_name)
                        st.success("Edited rows exported to Google Sheets.")
                    except GoogleSheetsError as exc:
                        st.error(str(exc))
                    finally:
                        if credential_path and credential_path.exists():
                            credential_path.unlink(missing_ok=True)

    with presets_tab:
        st.subheader("Tone presets")
        st.caption("The built-in library has 50 presets. Client-specific profiles are optional and are saved locally.")
        options = pd.DataFrame(preset_options())
        st.dataframe(options, use_container_width=True, height=620)


if __name__ == "__main__":
    main()
