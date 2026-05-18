from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from client_safe_export import create_client_safe_package
from batch_runner import run
from config import DATA_DIR, OUTPUT_DIR, load_settings
from cost_estimator import CostEstimate, estimate_batch_cost, price_for_model
from export import CLIENT_REVIEW_COLUMNS, _client_rows
from export_mappings import preset_names, sending_tool_dataframe
from google_sheets import (
    GoogleSheetsError,
    dataframe_to_temp_csv,
    export_dataframe_to_sheet,
    read_private_sheet,
    read_public_sheet,
)
from run_history import append_run_history, load_run_history
from preflight import has_blocking_failures, run_preflight
from sendability import (
    EDIT_REASON_CATEGORIES,
    GOLDSET_SPLITS,
    HUMAN_DECISIONS,
    append_goldset_feedback,
    apply_sendability_to_dataframe,
    goldset_paths,
    load_goldset_summary,
)
from tone_preset_library import get_preset_profile, preset_options
from tone_profiles import available_tone_profiles, load_tone_profile
from web_app_views import render_eval_tab, render_training_tab


DEFAULT_CONTEXT = "We help mobile app teams with this type of work, figure out where users drop off and why."
RUN_INPUT_DIR = DATA_DIR / "ui_uploads"
RUN_OUTPUT_DIR = OUTPUT_DIR / "ui_runs"
CUSTOM_PROFILE_DIR = DATA_DIR / "custom_tone_profiles"
SAMPLE_INPUT_PATH = DATA_DIR / "input" / "sample_companies.csv"
DELIVERY_COLUMNS = [
    "sendability_decision",
    "human_decision",
    "company",
    "person",
    "role",
    "website",
    "personalized_line",
    "option_1_line",
    "option_2_line",
    "option_3_line",
    "needs_manual_review",
    "quality_flags",
    "reviewer_notes",
]


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
    df = apply_sendability_to_dataframe(df)
    ordered = [
        "status",
        "sendability_decision",
        "sendability_score",
        "sendability_reasons",
        "hard_fail_reasons",
        "soft_edit_reasons",
        "evidence_score",
        "copy_quality_score",
        "outcome_alignment_score",
        "template_fit_score",
        "surface_correctness",
        "surface_correctness_score",
        "surface_correctness_reasons",
        "visual_reliability_score",
        "viewport_scope",
        "viewport_scope_score",
        "viewport_scope_reasons",
        "evidence_scope",
        "privacy_flags",
        "client_safe_asset_status",
        "sendability_dimensions",
        "human_decision",
        "edited_line",
        "edit_reason_category",
        "edit_notes",
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
        "product_surface_type",
        "research_priority",
        "visual_confidence",
        "visual_confidence_score",
        "visual_confidence_reasons",
        "visual_flags",
        "screenshots",
        "shareable_screenshots",
        "trace_files",
        "ux_validator_findings",
        "advanced_detector_flags",
        "dead_link_checks",
        "source_urls",
        "tone_profile",
        "model_provider",
        "model_name",
        "prompt_set_hash",
        "evidence_prompt_hash",
        "write_prompt_hash",
        "qc_prompt_hash",
        "tone_profile_hash",
    ]
    return df[[col for col in ordered if col in df.columns]]


def _delivery_df(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    if "human_decision" in prepared and "edited_line" in prepared and "personalized_line" in prepared:
        use_edit = (
            prepared["human_decision"].fillna("").astype(str).str.lower().isin({"send", "edit"})
            & prepared["edited_line"].fillna("").astype(str).str.strip().ne("")
        )
        prepared.loc[use_edit, "personalized_line"] = prepared.loc[use_edit, "edited_line"]
    columns = [column for column in DELIVERY_COLUMNS if column in df.columns]
    delivery = prepared[columns].copy()
    if "status" in prepared.columns:
        delivery.insert(0, "status", prepared["status"])
    return delivery


def _batch_summary(df: pd.DataFrame, cost: CostEstimate | None, output_path: Path, input_path: Path, tone_profile: str, provider: str, model_name: str) -> dict[str, Any]:
    total = len(df)
    ready = _count_status(df, "Ready")
    review = _count_status(df, "Review")
    research_only = _count_status(df, "Research only")
    sendable = int((df["sendability_decision"] == "Send").sum()) if "sendability_decision" in df else 0
    editable = int((df["sendability_decision"] == "Edit").sum()) if "sendability_decision" in df else 0
    rejected = int((df["sendability_decision"] == "Reject").sum()) if "sendability_decision" in df else 0
    surface_correct = int((df["surface_correctness"] == "Correct").sum()) if "surface_correctness" in df else 0
    surface_review = int((df["surface_correctness"] == "Review").sum()) if "surface_correctness" in df else 0
    surface_wrong = int((df["surface_correctness"] == "Wrong").sum()) if "surface_correctness" in df else 0
    unique_companies = df["company"].nunique() if "company" in df else 0
    return {
        "input_file": str(input_path),
        "output_file": str(output_path),
        "rows": total,
        "unique_companies": int(unique_companies),
        "ready_rows": ready,
        "review_rows": review,
        "research_only_rows": research_only,
        "sendability_send_rows": sendable,
        "sendability_edit_rows": editable,
        "sendability_reject_rows": rejected,
        "surface_correct_rows": surface_correct,
        "surface_review_rows": surface_review,
        "surface_wrong_rows": surface_wrong,
        "ready_rate": round(ready / total * 100, 1) if total else 0,
        "provider": provider,
        "model": model_name,
        "tone_profile": Path(tone_profile).stem if str(tone_profile).endswith(".json") else tone_profile,
        "prompt_set_hash": str(df["prompt_set_hash"].iloc[0]) if "prompt_set_hash" in df and not df.empty else "",
        "write_prompt_hash": str(df["write_prompt_hash"].iloc[0]) if "write_prompt_hash" in df and not df.empty else "",
        "qc_prompt_hash": str(df["qc_prompt_hash"].iloc[0]) if "qc_prompt_hash" in df and not df.empty else "",
        "tone_profile_hash": str(df["tone_profile_hash"].iloc[0]) if "tone_profile_hash" in df and not df.empty else "",
        "estimated_cost_usd": round(cost.estimated_cost_usd, 6) if cost else 0,
        "llm_calls": cost.llm_calls if cost else 0,
        "input_tokens": cost.input_tokens if cost else 0,
        "output_tokens": cost.output_tokens if cost else 0,
    }


def _df_to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Review")
        worksheet = writer.book["Review"]
        width_by_name = {
            "personalized_line": 72,
            "edited_line": 72,
            "template_preview": 84,
            "evidence_found": 84,
            "reviewer_notes": 66,
            "sendability_reasons": 52,
            "hard_fail_reasons": 44,
            "soft_edit_reasons": 44,
            "surface_correctness_reasons": 44,
            "viewport_scope_reasons": 44,
            "privacy_flags": 44,
            "sendability_dimensions": 44,
            "edit_notes": 52,
            "quality_flags": 42,
            "visual_confidence_reasons": 46,
            "source_urls": 48,
            "screenshots": 46,
            "shareable_screenshots": 46,
            "trace_files": 46,
        }
        for idx, column_name in enumerate(df.columns, 1):
            width = width_by_name.get(str(column_name), 22)
            worksheet.column_dimensions[worksheet.cell(1, idx).column_letter].width = width
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
        skip_preflight=False,
        sending_tool_preset="",
        sending_tool_output="",
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


def _set_detector_env(advanced_detectors: bool, lighthouse_review: bool) -> None:
    os.environ["ADVANCED_DETECTORS"] = "auto" if advanced_detectors else "off"
    os.environ["LIGHTHOUSE_REVIEW"] = "auto" if lighthouse_review else "off"


def _set_research_region_env(region: str) -> None:
    os.environ["RESEARCH_REGION"] = region.strip().lower()


def _sidebar_settings() -> tuple[str, str, str, float, float, bool, bool, str]:
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

    st.sidebar.header("Research detectors")
    advanced_detectors = st.sidebar.checkbox(
        "Playwright + axe checks",
        value=settings.advanced_detectors not in {"0", "false", "no", "off", "disabled"},
        help="Full-page screenshots, traces, visible CTA checks, dead-link candidates and axe-core accessibility signals.",
    )
    lighthouse_review = st.sidebar.checkbox(
        "Lighthouse checks",
        value=settings.lighthouse_review not in {"0", "false", "no", "off", "disabled"},
        help="Slower mobile quality audit. Use for deeper review, not every quick batch.",
    )
    st.sidebar.header("Research region")
    region_options = {
        "US App Store / US browser locale": "us",
        "UK App Store / UK browser locale": "uk",
        "Netherlands locale": "nl",
        "Canada locale": "ca",
        "Australia locale": "au",
        "Germany locale": "de",
    }
    region_values = list(region_options.values())
    region_labels = list(region_options.keys())
    current_region = settings.research_region if settings.research_region in region_values else "us"
    research_region = st.sidebar.selectbox(
        "Region",
        region_labels,
        index=region_values.index(current_region),
        help="Controls Apple review country plus browser locale/timezone. For true IP-region changes, also set a proxy/VPN URL.",
    )
    research_region_value = region_options[research_region]
    st.sidebar.caption("Dit is regio-emulatie. Een echte VPN/IP-regio vereist nog steeds een proxy/VPN.")
    st.sidebar.header("Pre-flight")
    if st.sidebar.button("Run system check", use_container_width=True):
        _set_api_env(provider, api_key, model_name)
        _set_detector_env(advanced_detectors, lighthouse_review)
        _set_research_region_env(research_region_value)
        checks = run_preflight(load_settings())
        for check in checks:
            if check.status == "ok":
                st.sidebar.success(f"{check.name}: {check.message}")
            elif check.status == "warn":
                st.sidebar.warning(f"{check.name}: {check.message}")
            else:
                st.sidebar.error(f"{check.name}: {check.message}")
        if has_blocking_failures(checks):
            st.sidebar.error("Fix blocking pre-flight failures before a large batch.")
        else:
            st.sidebar.success("Pre-flight passed without blocking failures.")
    return provider, model_name, api_key, input_price, output_price, advanced_detectors, lighthouse_review, research_region_value


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
    advanced_detectors: bool,
    lighthouse_review: bool,
    research_region: str,
) -> tuple[list[dict[str, Any]], Path]:
    _set_api_env(provider, api_key, model_name)
    _set_detector_env(advanced_detectors, lighthouse_review)
    _set_research_region_env(research_region)
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
    append_run_history(
        _batch_summary(
            st.session_state["review_df"],
            cost,
            output_path,
            input_path,
            tone_profile,
            provider,
            model_name,
        )
    )
    return rows, output_path


def _store_batch_result(
    rows: list[dict[str, Any]],
    output_path: Path,
    input_path: Path,
    tone_profile: str,
    provider: str,
    model_name: str,
    input_price: float,
    output_price: float,
) -> CostEstimate:
    cost = estimate_batch_cost(rows, input_price, output_price)
    for row in rows:
        row["estimated_model_cost_usd"] = round(cost.estimated_cost_usd, 6)
    st.session_state["rows"] = rows
    st.session_state["review_df"] = _rows_to_review_df(rows)
    st.session_state["output_path"] = str(output_path)
    st.session_state["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.session_state["cost_estimate"] = cost
    append_run_history(
        _batch_summary(
            st.session_state["review_df"],
            cost,
            output_path,
            input_path,
            tone_profile,
            provider,
            model_name,
        )
    )
    return cost


def _start_background_batch(
    input_path: Path,
    campaign_context: str,
    tone_profile: str,
    provider: str,
    model_name: str,
    api_key: str,
    input_price: float,
    output_price: float,
    advanced_detectors: bool,
    lighthouse_review: bool,
    research_region: str,
) -> None:
    progress_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    output_path = _output_path(input_path)
    job = {
        "queue": progress_queue,
        "started_at": time.time(),
        "last_progress": {"progress": 0.0, "stage": "Queued", "current": 0, "total": 0},
        "done": False,
    }
    st.session_state["batch_job"] = job

    def worker() -> None:
        try:
            _set_api_env(provider, api_key, model_name)
            _set_detector_env(advanced_detectors, lighthouse_review)
            _set_research_region_env(research_region)
            rows = run(
                _make_args(input_path, output_path, campaign_context, tone_profile),
                progress_callback=lambda payload: progress_queue.put({"type": "progress", **payload}),
            )
            progress_queue.put(
                {
                    "type": "done",
                    "rows": rows,
                    "output_path": str(output_path),
                    "input_path": str(input_path),
                    "tone_profile": tone_profile,
                    "provider": provider,
                    "model_name": model_name,
                    "input_price": input_price,
                    "output_price": output_price,
                }
            )
        except Exception as exc:
            progress_queue.put({"type": "error", "message": str(exc)})

    thread = threading.Thread(target=worker, name="email-personalizer-batch", daemon=True)
    job["thread"] = thread
    thread.start()


def _render_background_batch_status() -> None:
    job = st.session_state.get("batch_job")
    if not job:
        return
    progress_queue = job.get("queue")
    if not isinstance(progress_queue, queue.Queue):
        return

    while True:
        try:
            event = progress_queue.get_nowait()
        except queue.Empty:
            break
        event_type = event.get("type")
        if event_type == "progress":
            job["last_progress"] = event
        elif event_type == "done":
            rows = event["rows"]
            output_path = Path(event["output_path"])
            input_path = Path(event["input_path"])
            _store_batch_result(
                rows,
                output_path,
                input_path,
                event["tone_profile"],
                event["provider"],
                event["model_name"],
                float(event["input_price"]),
                float(event["output_price"]),
            )
            st.session_state.pop("batch_job", None)
            st.success(f"Batch ready: {len(rows)} rows. Output saved to {output_path}")
            return
        elif event_type == "error":
            st.session_state.pop("batch_job", None)
            st.error(event.get("message", "Batch failed."))
            return

    last = job.get("last_progress", {})
    progress = max(0.0, min(1.0, float(last.get("progress", 0.0))))
    current = last.get("current", 0)
    total = last.get("total", 0)
    stage = last.get("stage", "Running")
    company = last.get("company", "")
    suffix = f" - {company}" if company else ""
    st.progress(progress, text=f"{stage}: {current}/{total}{suffix}")
    st.caption("Batch is running in the background. The UI will refresh while progress updates arrive.")
    time.sleep(0.8)
    st.rerun()


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
    sendable = int((df["sendability_decision"] == "Send").sum()) if "sendability_decision" in df else 0
    editable = int((df["sendability_decision"] == "Edit").sum()) if "sendability_decision" in df else 0
    rejected = int((df["sendability_decision"] == "Reject").sum()) if "sendability_decision" in df else 0
    avg_evidence = round(pd.to_numeric(df.get("evidence_score", pd.Series(dtype=float)), errors="coerce").dropna().mean(), 1) if "evidence_score" in df else 0
    avg_surface = round(pd.to_numeric(df.get("surface_correctness_score", pd.Series(dtype=float)), errors="coerce").dropna().mean(), 1) if "surface_correctness_score" in df else 0

    st.subheader("Batch dashboard")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Rows", total, f"{unique_companies} unique companies")
    c2.metric("Send", sendable, f"{round(sendable / total * 100) if total else 0}%")
    c3.metric("Edit", editable)
    c4.metric("Reject", rejected)
    c5.metric("Evidence", avg_evidence if avg_evidence == avg_evidence else 0)
    c6.metric("Surface", avg_surface if avg_surface == avg_surface else 0)
    st.caption(f"Status layer: {ready} Ready, {review} Review, {research_only} Research only. Sendability is the stricter client-delivery gate.")

    if cost:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("LLM calls", cost.llm_calls)
        k2.metric("Input tokens", f"{cost.input_tokens:,}")
        k3.metric("Output tokens", f"{cost.output_tokens:,}")
        k4.metric("Est. model cost", f"${cost.estimated_cost_usd:.4f}", f"${cost.cost_per_row_usd:.5f}/row")

    left, right = st.columns(2, gap="large")
    with left:
        sendability_counts = (
            df["sendability_decision"].fillna("Unknown").replace("", "Unknown").value_counts().rename_axis("decision").reset_index(name="rows")
            if "sendability_decision" in df
            else pd.DataFrame()
        )
        if not sendability_counts.empty:
            st.markdown("**Sendability gate**")
            st.bar_chart(sendability_counts.set_index("decision"))

        status_counts = df["status"].value_counts().rename_axis("status").reset_index(name="rows") if "status" in df else pd.DataFrame()
        if not status_counts.empty:
            st.markdown("**Status distribution**")
            st.bar_chart(status_counts.set_index("status"))

        hard_fails = _top_split_counts(df, "hard_fail_reasons", 8)
        if not hard_fails.empty:
            st.markdown("**Hard fail reasons**")
            st.bar_chart(hard_fails.set_index("label"))

    with right:
        sendability_reasons = _top_split_counts(df, "sendability_reasons", 8)
        if not sendability_reasons.empty:
            st.markdown("**Top sendability reasons**")
            st.bar_chart(sendability_reasons.set_index("label"))

        surface_counts = (
            df["surface_correctness"].fillna("Unknown").replace("", "Unknown").value_counts().rename_axis("surface").reset_index(name="rows")
            if "surface_correctness" in df
            else pd.DataFrame()
        )
        if not surface_counts.empty:
            st.markdown("**Surface correctness**")
            st.bar_chart(surface_counts.set_index("surface"))

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

    review_cols = [
        col
        for col in [
            "sendability_decision",
            "sendability_score",
            "surface_correctness",
            "company",
            "person",
            "personalized_line",
            "option_1_line",
            "option_2_line",
            "option_3_line",
            "sendability_reasons",
            "hard_fail_reasons",
            "soft_edit_reasons",
            "quality_flags",
            "visual_confidence",
            "reviewer_notes",
        ]
        if col in df
    ]
    st.markdown("**Review queue**")
    if review_cols:
        if "sendability_decision" in df:
            queue = df[df["sendability_decision"].isin(["Edit", "Reject"])]
        else:
            queue = df[df["status"].isin(["Review", "Research only"])] if "status" in df else df
        st.dataframe(queue[review_cols], use_container_width=True, height=300)


def _focused_review_panel(filtered: pd.DataFrame) -> None:
    if filtered.empty:
        st.info("No rows match the current filters.")
        return
    priority = filtered.copy()
    if "sendability_decision" in priority:
        priority["_sort"] = priority["sendability_decision"].map({"Edit": 0, "Reject": 1, "Send": 2}).fillna(3)
        priority = priority.sort_values(["_sort"])
    labels: list[str] = []
    index_by_label: dict[str, Any] = {}
    for idx, row in priority.iterrows():
        company = str(row.get("company", "Company") or "Company")
        person = str(row.get("person", "") or "").strip()
        decision = str(row.get("sendability_decision", "") or "").strip()
        label = f"{idx} | {company}" + (f" / {person}" if person else "") + (f" [{decision}]" if decision else "")
        labels.append(label)
        index_by_label[label] = idx
    selected_label = st.selectbox("Focused row", labels, key="focused_review_row")
    selected_idx = index_by_label[selected_label]
    row = st.session_state["review_df"].loc[selected_idx]

    line = str(row.get("edited_line") or row.get("personalized_line") or "")
    preview = str(row.get("template_preview") or f"Hey {row.get('person', '[Name]')}\n\n{line}\n\n{DEFAULT_CONTEXT}")
    option_lines = [
        str(row.get(f"option_{index}_line", "") or "").strip()
        for index in range(1, 4)
        if str(row.get(f"option_{index}_line", "") or "").strip()
    ]
    evidence = str(row.get("evidence_found") or row.get("evidence_used_for_copy") or "")
    sources = str(row.get("source_urls") or "")
    reasons = " | ".join(
        str(row.get(column, "") or "")
        for column in ["hard_fail_reasons", "soft_edit_reasons", "quality_flags", "reviewer_notes"]
        if str(row.get(column, "") or "").strip()
    )

    left, right = st.columns([1.05, 1])
    with left:
        st.markdown("**Evidence to verify**")
        st.text_area("Evidence", evidence, height=150, disabled=True, label_visibility="collapsed")
        if sources:
            st.caption(f"Sources: {sources}")
        st.markdown("**Why this needs attention**")
        st.text_area("Reasons", reasons or "No major flags.", height=110, disabled=True, label_visibility="collapsed")
    with right:
        st.markdown("**Email preview**")
        st.text_area("Preview", preview, height=150, disabled=True, label_visibility="collapsed")
        if option_lines:
            st.markdown("**Generated options**")
            for option_number, option_line in enumerate(option_lines, 1):
                st.caption(f"Option {option_number}")
                st.text_area(
                    f"Option {option_number}",
                    option_line,
                    height=70,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"focus_option_{selected_idx}_{option_number}",
                )
        current_decision = str(row.get("human_decision", "unreviewed") or "unreviewed").lower()
        decision_index = HUMAN_DECISIONS.index(current_decision) if current_decision in HUMAN_DECISIONS else 0
        human_decision = st.selectbox("Decision", HUMAN_DECISIONS, index=decision_index, key=f"focus_decision_{selected_idx}")
        edited_line = st.text_area("Edited line", str(row.get("edited_line", "") or ""), height=92, key=f"focus_edit_{selected_idx}")
        current_reason = str(row.get("edit_reason_category", "not_reviewed") or "not_reviewed")
        reason_index = EDIT_REASON_CATEGORIES.index(current_reason) if current_reason in EDIT_REASON_CATEGORIES else 0
        edit_reason = st.selectbox("Edit reason", EDIT_REASON_CATEGORIES, index=reason_index, key=f"focus_reason_{selected_idx}")
        edit_notes = st.text_area("Review notes", str(row.get("edit_notes", "") or ""), height=70, key=f"focus_notes_{selected_idx}")
        if st.button("Save focused review", use_container_width=True):
            updated = st.session_state["review_df"].copy()
            updated.at[selected_idx, "human_decision"] = human_decision
            updated.at[selected_idx, "edited_line"] = edited_line
            updated.at[selected_idx, "edit_reason_category"] = edit_reason
            updated.at[selected_idx, "edit_notes"] = edit_notes
            st.session_state["review_df"] = apply_sendability_to_dataframe(updated)
            st.success("Focused review saved.")


def _how_it_works_panel() -> None:
    st.subheader("Client-facing workflow")
    st.markdown(
        """
        <div class="ux-card">
            <span class="ux-badge">1 Lead list</span>
            <span class="ux-badge">2 Public research</span>
            <span class="ux-badge">3 Evidence extraction</span>
            <span class="ux-badge">4 Friction angle</span>
            <span class="ux-badge">5 Tone profile</span>
            <span class="ux-badge">6 Draft line</span>
            <span class="ux-badge">7 QC</span>
            <span class="ux-badge">8 Sendability gate</span>
            <span class="ux-badge">9 Human review</span>
            <p class="ux-muted" style="margin-top:12px;">
            The system does not start by asking a model to write a clever opener. It first gathers public evidence,
            selects a current friction point or proof gap, then writes a short line that can be checked against the source.
            Rows with weak evidence, low visual confidence, or uncertain claims are separated into Send, Edit or Reject.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Research surfaces**")
        st.write("Homepage, product pages, pricing, case studies, testimonials, app pages, public app listings and screenshots.")
    with col2:
        st.markdown("**Preferred angles**")
        st.write("Broken formatting, unclear CTA, onboarding friction, booking/signup friction, weak proof and broad positioning.")
    with col3:
        st.markdown("**Review logic**")
        st.write("No em dashes, no generic praise, no unsupported claims, no blog-post filler, and a goldset of human edits for future tuning.")


def _tone_calibration_panel() -> None:
    st.subheader("Tone calibration")
    st.caption("Paste client feedback here to save a reusable client profile. This is optional; presets still work by themselves.")
    base_profiles = available_tone_profiles()
    base_index = base_profiles.index("friction_first") if "friction_first" in base_profiles else 0
    base = st.selectbox("Base profile", base_profiles, index=base_index, key="calibration_base_profile")
    client_name = st.text_input("Client/profile name", value="client_profile", key="calibration_client_name")
    feedback = st.text_area("Client feedback / new rules", height=150, key="calibration_feedback")
    good_examples = st.text_area("Good examples, one per line", height=110, key="calibration_good")
    bad_examples = st.text_area("Bad examples, one per line", height=110, key="calibration_bad")
    if st.button("Save client tone profile", type="primary", use_container_width=True):
        if not client_name.strip():
            st.error("Add a client/profile name first.")
            return
        path = _custom_profile_path(base, client_name, feedback, good_examples, bad_examples)
        st.session_state["preferred_tone_profile"] = path.stem
        st.success(f"Saved profile: {path.name}")
        st.caption(f"It will appear in the tone profile dropdown as `{path.stem}`.")


def _history_panel() -> None:
    st.subheader("Batch history")
    history = load_run_history()
    if history.empty:
        st.info("No run history yet. Run a batch first.")
        return
    visible_columns = [
        column
        for column in [
            "created_at",
            "rows",
            "unique_companies",
            "ready_rows",
            "review_rows",
            "research_only_rows",
            "sendability_send_rows",
            "sendability_edit_rows",
            "sendability_reject_rows",
            "surface_correct_rows",
            "surface_review_rows",
            "surface_wrong_rows",
            "ready_rate",
            "estimated_cost_usd",
            "provider",
            "model",
            "tone_profile",
            "output_file",
        ]
        if column in history.columns
    ]
    st.dataframe(history[visible_columns], use_container_width=True, height=360)
    output_files = [str(path) for path in history.get("output_file", pd.Series(dtype=str)).dropna().tolist() if Path(str(path)).exists()]
    if output_files:
        selected = st.selectbox("Load/download previous workbook", output_files)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Load review sheet into app", use_container_width=True):
                try:
                    st.session_state["review_df"] = apply_sendability_to_dataframe(pd.read_excel(selected, sheet_name="Review").fillna(""))
                    st.session_state["output_path"] = selected
                    st.success("Previous run loaded into Review & Edit.")
                except Exception as exc:
                    st.error(f"Could not load workbook: {exc}")
        with c2:
            st.download_button(
                "Download selected workbook",
                Path(selected).read_bytes(),
                Path(selected).name,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )


def _profile_picker() -> str:
    tone_names = available_tone_profiles()
    preferred = st.session_state.get("preferred_tone_profile", "friction_first")
    default_index = tone_names.index(preferred) if preferred in tone_names else tone_names.index("friction_first") if "friction_first" in tone_names else 0
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

    provider, model_name, api_key, input_price, output_price, advanced_detectors, lighthouse_review, research_region = _sidebar_settings()

    dashboard_tab, setup_tab, review_tab, export_tab, training_tab, eval_tab, calibration_tab, history_tab, presets_tab = st.tabs(
        ["Dashboard", "Setup & Run", "Review & Edit", "Export", "Client Training", "Evals", "Tone Calibration", "History", "Tone Presets"]
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
        _how_it_works_panel()

    with setup_tab:
        left, right = st.columns([1.05, 0.95], gap="large")
        with left:
            st.subheader("1. Input")
            input_source = st.radio("Lead source", ["CSV upload", "Google Sheets", "Demo sample"], horizontal=True)
            input_path: Path | None = None
            uploaded_file = None
            sheet_url = ""
            worksheet_name = ""
            sheet_service_file = None

            if input_source == "CSV upload":
                uploaded_file = st.file_uploader("Lead CSV", type=["csv"])
            elif input_source == "Google Sheets":
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
            else:
                st.info("Demo sample selected. This uses the built-in sample CSV so you can show the workflow without preparing a file.")
                if SAMPLE_INPUT_PATH.exists():
                    st.dataframe(pd.read_csv(SAMPLE_INPUT_PATH, dtype=str).fillna("").head(10), use_container_width=True)
                else:
                    st.error(f"Sample file not found: {SAMPLE_INPUT_PATH}")

            st.subheader("2. Campaign context")
            campaign_context = st.text_area(
                "Sentence after the personalized line",
                value=DEFAULT_CONTEXT,
                height=95,
            )

            st.subheader("3. Tone")
            tone_for_run = _profile_picker()

            _render_background_batch_status()
            batch_running = "batch_job" in st.session_state
            if st.button("Run batch", type="primary", use_container_width=True):
                try:
                    if batch_running:
                        st.warning("A batch is already running.")
                        st.stop()
                    if input_source == "CSV upload":
                        if uploaded_file is None:
                            st.error("Upload a CSV first.")
                            st.stop()
                        input_path = _write_uploaded_csv(uploaded_file)
                    elif input_source == "Google Sheets":
                        if not sheet_url.strip():
                            st.error("Paste a Google Sheets URL first.")
                            st.stop()
                        input_path = _load_google_sheet_to_csv(sheet_url, worksheet_name, sheet_service_file)
                    else:
                        if not SAMPLE_INPUT_PATH.exists():
                            st.error("Sample CSV is missing.")
                            st.stop()
                        input_path = SAMPLE_INPUT_PATH
                    _start_background_batch(
                        input_path,
                        campaign_context,
                        tone_for_run,
                        provider,
                        model_name,
                        api_key,
                        input_price,
                        output_price,
                        advanced_detectors,
                        lighthouse_review,
                        research_region,
                    )
                    st.rerun()
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
                    <span class="ux-badge">7 Sendability</span>
                    <span class="ux-badge">8 Review</span>
                    <span class="ux-badge">9 Export</span>
                    <p class="ux-muted" style="margin-top:12px;">
                    Weak evidence remains visible. Sendability, visual confidence and review flags decide what needs checking before delivery.
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
            decision_options = df["sendability_decision"].dropna().unique().tolist() if "sendability_decision" in df else []
            decision_filter = st.multiselect(
                "Filter sendability",
                sorted(decision_options),
                default=sorted(decision_options),
            )
            surface_options = df["surface_correctness"].dropna().unique().tolist() if "surface_correctness" in df else []
            surface_filter = st.multiselect(
                "Filter surface correctness",
                sorted(surface_options),
                default=sorted(surface_options),
            )
            filtered = df[df["status"].isin(status_filter)] if status_filter and "status" in df else df
            if decision_filter and "sendability_decision" in filtered:
                filtered = filtered[filtered["sendability_decision"].isin(decision_filter)]
            if surface_filter and "surface_correctness" in filtered:
                filtered = filtered[filtered["surface_correctness"].isin(surface_filter)]
            st.caption("Use `human_decision`, `edited_line`, and `edit_reason_category` to turn reviewed rows into a reusable goldset.")
            with st.expander("Fast focused review", expanded=True):
                _focused_review_panel(filtered)
            edited = st.data_editor(
                filtered,
                use_container_width=True,
                height=650,
                num_rows="fixed",
                disabled=[
                    "sendability_decision",
                    "sendability_score",
                    "sendability_reasons",
                    "hard_fail_reasons",
                    "soft_edit_reasons",
                    "evidence_score",
                    "copy_quality_score",
                    "outcome_alignment_score",
                    "template_fit_score",
                    "surface_correctness",
                    "surface_correctness_score",
                    "surface_correctness_reasons",
                    "visual_reliability_score",
                    "viewport_scope",
                    "viewport_scope_score",
                    "viewport_scope_reasons",
                    "evidence_scope",
                    "privacy_flags",
                    "client_safe_asset_status",
                    "sendability_dimensions",
                ],
                column_config={
                    "sendability_decision": st.column_config.TextColumn("sendability_decision", width="small"),
                    "sendability_score": st.column_config.NumberColumn("sendability_score", width="small"),
                    "sendability_reasons": st.column_config.TextColumn("sendability_reasons", width="large"),
                    "hard_fail_reasons": st.column_config.TextColumn("hard_fail_reasons", width="large"),
                    "soft_edit_reasons": st.column_config.TextColumn("soft_edit_reasons", width="large"),
                    "evidence_score": st.column_config.NumberColumn("evidence_score", width="small"),
                    "copy_quality_score": st.column_config.NumberColumn("copy_quality_score", width="small"),
                    "outcome_alignment_score": st.column_config.NumberColumn("outcome_alignment_score", width="small"),
                    "template_fit_score": st.column_config.NumberColumn("template_fit_score", width="small"),
                    "surface_correctness": st.column_config.TextColumn("surface_correctness", width="small"),
                    "surface_correctness_score": st.column_config.NumberColumn("surface_correctness_score", width="small"),
                    "surface_correctness_reasons": st.column_config.TextColumn("surface_correctness_reasons", width="large"),
                    "visual_reliability_score": st.column_config.NumberColumn("visual_reliability_score", width="small"),
                    "viewport_scope": st.column_config.TextColumn("viewport_scope", width="small"),
                    "viewport_scope_score": st.column_config.NumberColumn("viewport_scope_score", width="small"),
                    "viewport_scope_reasons": st.column_config.TextColumn("viewport_scope_reasons", width="large"),
                    "evidence_scope": st.column_config.TextColumn("evidence_scope", width="small"),
                    "privacy_flags": st.column_config.TextColumn("privacy_flags", width="large"),
                    "client_safe_asset_status": st.column_config.TextColumn("client_safe_asset_status", width="small"),
                    "sendability_dimensions": st.column_config.TextColumn("sendability_dimensions", width="large"),
                    "human_decision": st.column_config.SelectboxColumn("human_decision", options=HUMAN_DECISIONS),
                    "edited_line": st.column_config.TextColumn("edited_line", width="large"),
                    "edit_reason_category": st.column_config.SelectboxColumn("edit_reason_category", options=EDIT_REASON_CATEGORIES),
                    "edit_notes": st.column_config.TextColumn("edit_notes", width="large"),
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
                st.session_state["review_df"] = apply_sendability_to_dataframe(updated)
                st.success("Edits saved in this session.")
            c1, c2 = st.columns(2)
            if c1.button("Apply edited lines to current personalization", use_container_width=True):
                updated = st.session_state["review_df"].copy()
                if {"human_decision", "edited_line", "personalized_line"}.issubset(updated.columns):
                    mask = (
                        updated["human_decision"].fillna("").astype(str).str.lower().isin({"send", "edit"})
                        & updated["edited_line"].fillna("").astype(str).str.strip().ne("")
                    )
                    updated.loc[mask, "personalized_line"] = updated.loc[mask, "edited_line"]
                    st.session_state["review_df"] = apply_sendability_to_dataframe(updated)
                    st.success(f"Applied edited lines to {int(mask.sum())} rows. Original model lines were preserved for goldset/training.")
            goldset_split = st.selectbox(
                "Goldset destination",
                GOLDSET_SPLITS,
                help="Use reviewed_examples for normal review data, frozen_eval_set for locked regression tests, or candidate_training_set for future tuning examples.",
            )
            if c2.button("Save reviewed rows to goldset", use_container_width=True):
                path, count = append_goldset_feedback(st.session_state["review_df"], split=goldset_split)
                if count:
                    st.success(f"Saved {count} reviewed rows to {path}")
                else:
                    st.info("No reviewed rows yet. Set human_decision to send, edit, or reject first.")

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
                package_path = Path(output_path).with_name(f"{Path(output_path).stem}_delivery_package.zip")
                if package_path.exists():
                    st.download_button(
                        "Download workbook + screenshot package",
                        package_path.read_bytes(),
                        package_path.name,
                        "application/zip",
                        use_container_width=True,
                    )

            st.markdown("**Client delivery export**")
            delivery = _delivery_df(df)
            delivery_filter = st.radio(
                "Rows for client delivery",
                ["All rows", "Sendability: Send only", "Human-approved send/edit only"],
                horizontal=True,
            )
            if delivery_filter == "Sendability: Send only" and "sendability_decision" in delivery:
                delivery = delivery[delivery["sendability_decision"] == "Send"]
            elif delivery_filter == "Human-approved send/edit only" and "human_decision" in delivery:
                delivery = delivery[delivery["human_decision"].fillna("").astype(str).str.lower().isin({"send", "edit"})]
            delivery_columns = st.multiselect(
                "Columns for client delivery",
                delivery.columns.tolist(),
                default=[column for column in ["company", "person", "role", "personalized_line"] if column in delivery.columns],
            )
            delivery_out = delivery[delivery_columns] if delivery_columns else delivery
            d1, d2 = st.columns(2)
            d1.download_button(
                "Download client delivery CSV",
                delivery_out.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                "client_delivery_personalized_lines.csv",
                "text/csv",
                use_container_width=True,
            )
            d2.download_button(
                "Download client delivery XLSX",
                _df_to_xlsx_bytes(delivery_out),
                "client_delivery_personalized_lines.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            st.markdown("**Sending tool mapping**")
            mapping_preset = st.selectbox(
                "Native export format",
                preset_names(),
                index=preset_names().index("generic"),
                help="Creates a CSV/XLSX with column names matching common sending tools, so manual mapping is reduced.",
            )
            mapped_delivery = sending_tool_dataframe(delivery, preset=mapping_preset)
            m1, m2 = st.columns(2)
            m1.download_button(
                f"Download {mapping_preset} CSV",
                mapped_delivery.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                f"{mapping_preset}_personalization_import.csv",
                "text/csv",
                use_container_width=True,
            )
            m2.download_button(
                f"Download {mapping_preset} XLSX",
                _df_to_xlsx_bytes(mapped_delivery),
                f"{mapping_preset}_personalization_import.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            base_dir = Path(output_path).parent if output_path else None
            if st.button("Create client-safe delivery package", use_container_width=True):
                try:
                    package = create_client_safe_package(df, base_dir=base_dir)
                    st.session_state["client_safe_package"] = str(package)
                    st.success(f"Client-safe package created: {package}")
                except Exception as exc:
                    st.error(f"Could not create client-safe package: {exc}")
            safe_package = st.session_state.get("client_safe_package")
            if safe_package and Path(safe_package).exists():
                st.download_button(
                    "Download client-safe package",
                    Path(safe_package).read_bytes(),
                    Path(safe_package).name,
                    "application/zip",
                    use_container_width=True,
                )
            st.caption("Client-safe packages exclude raw traces, internal detector output, and local file paths. Use the full workbook/package only for internal debugging.")

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

            with st.expander("Goldset export for future tuning"):
                summary = load_goldset_summary()
                st.dataframe(summary, use_container_width=True, hide_index=True)
                for split, goldset_path in goldset_paths().items():
                    if goldset_path.exists():
                        st.download_button(
                            f"Download {split}",
                            goldset_path.read_bytes(),
                            goldset_path.name,
                            "text/csv",
                            use_container_width=True,
                        )
                if not any(path.exists() for path in goldset_paths().values()):
                    st.caption("No saved goldset yet. Review rows first, then click `Save reviewed rows to goldset`.")

    with eval_tab:
        render_eval_tab()

    with training_tab:
        render_training_tab()

    with calibration_tab:
        _tone_calibration_panel()

    with history_tab:
        _history_panel()

    with presets_tab:
        st.subheader("Tone presets")
        st.caption("The built-in library has 50 presets. Client-specific profiles are optional and are saved locally.")
        options = pd.DataFrame(preset_options())
        st.dataframe(options, use_container_width=True, height=620)


if __name__ == "__main__":
    main()
