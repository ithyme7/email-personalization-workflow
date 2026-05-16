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
from export import CLIENT_REVIEW_COLUMNS, _client_rows
from tone_preset_library import get_preset_profile, preset_options
from tone_profiles import available_tone_profiles


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
        .block-container { padding-top: 1.6rem; }
        div[data-testid="stMetric"] {
            background: #111827;
            border: 1px solid #334155;
            padding: 16px;
            border-radius: 8px;
        }
        .ux-card {
            border: 1px solid #334155;
            background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
            border-radius: 8px;
            padding: 18px;
            min-height: 112px;
        }
        .ux-muted { color: #CBD5E1; font-size: 0.92rem; }
        .ux-badge {
            display: inline-block;
            border: 1px solid #334155;
            border-radius: 999px;
            padding: 4px 10px;
            color: #E2E8F0;
            margin-right: 6px;
            font-size: 0.78rem;
        }
        .stButton > button {
            border-radius: 8px;
            font-weight: 700;
        }
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


def _output_path(input_path: Path) -> Path:
    RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return RUN_OUTPUT_DIR / f"{input_path.stem}_review_{stamp}.xlsx"


def _profile_description(name: str) -> str:
    profile = get_preset_profile(name)
    if profile:
        return profile.description
    return "Custom JSON tone profile from the tone_profiles folder."


def _custom_profile_path(
    preset_name: str,
    custom_name: str,
    custom_prompt: str,
    good_examples: str,
    bad_examples: str,
) -> Path:
    CUSTOM_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    base = get_preset_profile(preset_name)
    if base is None:
        from tone_profiles import load_tone_profile

        base = load_tone_profile(preset_name)

    name = _safe_name(custom_name or f"custom_{preset_name}")
    payload = base.to_prompt_payload()
    payload["name"] = name
    payload["description"] = f"Custom profile based on {preset_name}. {payload.get('description', '')}".strip()
    payload["custom_prompt"] = custom_prompt.strip()
    if good_examples.strip():
        payload["example_good_lines"] = [
            line.strip()
            for line in good_examples.splitlines()
            if line.strip()
        ]
    if bad_examples.strip():
        payload["example_bad_lines"] = [
            line.strip()
            for line in bad_examples.splitlines()
            if line.strip()
        ]
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
            "F": 74,
            "G": 82,
            "H": 82,
            "I": 32,
            "J": 18,
            "K": 64,
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


def _sidebar_settings() -> tuple[str, str, str]:
    settings = load_settings()
    st.sidebar.header("Model")
    provider = st.sidebar.selectbox(
        "Provider",
        ["gemini", "openrouter", "deepseek", "openai"],
        index=["gemini", "openrouter", "deepseek", "openai"].index(settings.llm_provider),
    )
    default_model = settings.model_name
    model_name = st.sidebar.text_input("Model name", default_model)
    api_key = st.sidebar.text_input("API key for this run", type="password")
    st.sidebar.caption("Laat leeg voor research-only output. Keys worden niet in de code opgeslagen.")
    return provider, model_name, api_key


def _run_batch(uploaded_file, campaign_context: str, tone_profile: str, provider: str, model_name: str, api_key: str):
    _set_api_env(provider, api_key, model_name)
    input_path = _write_uploaded_csv(uploaded_file)
    output_path = _output_path(input_path)
    rows = run(_make_args(input_path, output_path, campaign_context, tone_profile))
    st.session_state["rows"] = rows
    st.session_state["review_df"] = _rows_to_review_df(rows)
    st.session_state["output_path"] = str(output_path)
    st.session_state["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return rows, output_path


def main() -> None:
    _inject_css()
    st.title("Email Personalization Workflow")
    st.caption("CSV in, researched personalization out. Evidence-first, reviewable, and built for human-in-the-loop delivery.")

    provider, model_name, api_key = _sidebar_settings()

    setup_tab, review_tab, export_tab, presets_tab = st.tabs(["Setup & Run", "Review & Edit", "Export", "Tone Presets"])

    with setup_tab:
        left, right = st.columns([1.1, 0.9], gap="large")
        with left:
            st.subheader("1. Upload CSV")
            uploaded_file = st.file_uploader("Lead CSV", type=["csv"])

            st.subheader("2. Campaign context")
            campaign_context = st.text_area(
                "The sentence after the personalized line",
                value=DEFAULT_CONTEXT,
                height=100,
            )

            st.subheader("3. Tone profile")
            tone_names = available_tone_profiles()
            selected_tone = st.selectbox("Choose one of 50 presets", tone_names, index=tone_names.index("friction_first") if "friction_first" in tone_names else 0)
            st.info(_profile_description(selected_tone))

            with st.expander("Create a custom prompt/profile"):
                use_custom = st.checkbox("Use custom prompt for this run")
                custom_name = st.text_input("Custom profile name", value=f"custom_{selected_tone}")
                custom_prompt = st.text_area(
                    "Custom prompt / tone guidance",
                    placeholder="Example: Make the line more founder-casual, avoid formal audit language, prioritize signup friction over proof gaps.",
                    height=150,
                )
                good_examples = st.text_area("Good example lines, one per line", height=110)
                bad_examples = st.text_area("Bad example lines, one per line", height=110)

            run_disabled = uploaded_file is None
            if st.button("Run batch", type="primary", disabled=run_disabled, use_container_width=True):
                tone_for_run = selected_tone
                if use_custom:
                    tone_for_run = str(_custom_profile_path(selected_tone, custom_name, custom_prompt, good_examples, bad_examples))
                with st.spinner("Running research, evidence extraction, writing and QC..."):
                    rows, output_path = _run_batch(uploaded_file, campaign_context, tone_for_run, provider, model_name, api_key)
                st.success(f"Batch klaar: {len(rows)} rows. Output: {output_path}")

        with right:
            st.subheader("Workflow")
            st.markdown(
                """
                <div class="ux-card">
                    <span class="ux-badge">1 CSV</span>
                    <span class="ux-badge">2 Research</span>
                    <span class="ux-badge">3 Evidence</span>
                    <span class="ux-badge">4 Write</span>
                    <span class="ux-badge">5 QC</span>
                    <span class="ux-badge">6 Review</span>
                    <p class="ux-muted" style="margin-top:14px;">
                    Weak evidence stays visible. Low-confidence visual findings and app-first rows are flagged for review.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if "review_df" in st.session_state:
                df = st.session_state["review_df"]
                ready = int((df["status"] == "Ready").sum()) if "status" in df else 0
                review = int((df["status"] == "Review").sum()) if "status" in df else 0
                research_only = int((df["status"] == "Research only").sum()) if "status" in df else 0
                c1, c2, c3 = st.columns(3)
                c1.metric("Rows", len(df))
                c2.metric("Ready", ready)
                c3.metric("Review", review + research_only)
                st.caption(f"Last run: {st.session_state.get('last_run_at', '-')}")

    with review_tab:
        if "review_df" not in st.session_state:
            st.info("Run a batch first. The editable review table will appear here.")
        else:
            st.subheader("Review and edit rows")
            df = st.session_state["review_df"].copy()
            status_filter = st.multiselect(
                "Filter status",
                sorted(df["status"].dropna().unique().tolist()) if "status" in df else [],
                default=sorted(df["status"].dropna().unique().tolist()) if "status" in df else [],
            )
            filtered = df[df["status"].isin(status_filter)] if status_filter and "status" in df else df
            edited = st.data_editor(
                filtered,
                use_container_width=True,
                height=620,
                num_rows="fixed",
                column_config={
                    "personalized_line": st.column_config.TextColumn("personalized_line", width="large"),
                    "template_preview": st.column_config.TextColumn("template_preview", width="large"),
                    "evidence_found": st.column_config.TextColumn("evidence_found", width="large"),
                    "reviewer_notes": st.column_config.TextColumn("reviewer_notes", width="large"),
                    "needs_manual_review": st.column_config.SelectboxColumn("needs_manual_review", options=["yes", "no"]),
                    "status": st.column_config.SelectboxColumn("status", options=["Ready", "Review", "Research only"]),
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

    with presets_tab:
        st.subheader("50 tone presets")
        options = pd.DataFrame(preset_options())
        st.dataframe(options, use_container_width=True, height=620)


if __name__ == "__main__":
    main()
