from __future__ import annotations

from pathlib import Path

import streamlit as st

from campaign_feedback import append_campaign_feedback, campaign_feedback_template_bytes, load_campaign_feedback, normalize_campaign_feedback, read_campaign_feedback
from client_training import append_training_feedback_to_goldset, normalize_training_feedback, read_training_feedback, training_template_bytes
from eval_runner import evaluate_frozen_goldset, evaluate_release_gate, export_frozen_eval_report
from sendability import GOLDSET_SPLITS


def render_eval_tab() -> None:
    st.subheader("Frozen eval set")
    st.caption("Use this to check whether sendability thresholds still agree with your locked human-reviewed examples.")
    summary, detail = evaluate_frozen_goldset()
    if detail.empty:
        st.info("No frozen eval set yet. Save reviewed rows to `frozen_eval_set` from the Review & Edit tab first.")
        st.dataframe(summary, use_container_width=True, hide_index=True)
        return

    metrics = {str(row["metric"]): row["value"] for _, row in summary.iterrows()}
    gate_passed, gate_failures = evaluate_release_gate(summary)
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Frozen rows", metrics.get("frozen_eval_rows", 0))
    e2.metric("Agreement", f"{metrics.get('exact_gate_human_agreement_pct', 0)}%")
    e3.metric("Send precision", f"{metrics.get('send_precision_pct', 0)}%")
    e4.metric("False sends", metrics.get("false_send_rows", 0))
    if gate_passed:
        st.success("Release gate passes with the current thresholds.")
    else:
        st.error("Release gate fails. Fix these before treating this version as production-ready.")
        st.write("\n".join(f"- {failure}" for failure in gate_failures))
    st.markdown("**Eval summary**")
    st.dataframe(summary, use_container_width=True, hide_index=True)
    left, right = st.columns(2)
    with left:
        st.markdown("**Gate decisions**")
        st.bar_chart(detail["gate_decision"].value_counts())
    with right:
        st.markdown("**Human decisions**")
        st.bar_chart(detail["human_decision"].value_counts())
    st.markdown("**Rows needing attention**")
    attention = detail[(detail["agreement"] == "no") | (detail["false_send"] == "yes")]
    st.dataframe(attention if not attention.empty else detail.head(0), use_container_width=True, height=280)
    st.markdown("**Full eval details**")
    st.dataframe(detail, use_container_width=True, height=360)
    if st.button("Export frozen eval report", use_container_width=True):
        report = export_frozen_eval_report()
        st.session_state["eval_report_path"] = str(report)
        st.success(f"Eval report created: {report}")
    eval_report = st.session_state.get("eval_report_path")
    if eval_report and Path(eval_report).exists():
        st.download_button(
            "Download eval report",
            Path(eval_report).read_bytes(),
            Path(eval_report).name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


def render_training_tab() -> None:
    st.subheader("Client training pack")
    st.caption("Give this to a client so they can label examples in plain English. Import it back to build a training/eval goldset.")
    st.markdown(
        """
        <div class="ux-card">
        <strong>How this works</strong>
        <p class="ux-muted">
        The client only chooses Send as is, Rewrite, or Reject. If they rewrite a line, that becomes the preferred example.
        The original line becomes the non-preferred example. This is the cleanest way to collect future fine-tuning or preference data.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    source = st.radio("Template source", ["Current review rows", "Blank template"], horizontal=True)
    template_df = st.session_state.get("review_df") if source == "Current review rows" else None
    if source == "Current review rows" and template_df is None:
        st.info("Run or load a batch first, or choose Blank template.")
    else:
        st.download_button(
            "Download client training template",
            training_template_bytes(template_df),
            "client_training_feedback_template.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with st.expander("Message you can send to the client"):
        st.code(
            """I've attached a short feedback template.

For each line, just choose:
- Send as is
- Rewrite
- Reject

If you choose Rewrite, please write the version you'd actually want to send.
The most useful feedback is not a long explanation, but a few strong examples of what sounds right and what sounds wrong.

I'll use the completed sheet to tune the workflow/model around your preferred tone and decision criteria.""",
            language="text",
        )

    st.markdown("**Import completed client feedback**")
    completed_feedback = st.file_uploader("Completed training template", type=["xlsx", "csv"], key="client_training_upload")
    training_import_splits = [split for split in GOLDSET_SPLITS if split != "frozen_eval_set"]
    training_split = st.selectbox(
        "Save imported feedback to",
        training_import_splits,
        index=training_import_splits.index("candidate_training_set") if "candidate_training_set" in training_import_splits else 0,
        key="training_goldset_split",
        help="Client feedback is not written directly to frozen_eval_set. Review/promote it intentionally after import.",
    )
    if completed_feedback is not None:
        try:
            raw_feedback = read_training_feedback(completed_feedback)
            normalized_feedback = normalize_training_feedback(raw_feedback)
            st.markdown("**Preview normalized training rows**")
            if normalized_feedback.empty:
                st.warning("No rows with a client_decision were found yet.")
            else:
                st.dataframe(normalized_feedback, use_container_width=True, height=320)
            if st.button("Import feedback into goldset", use_container_width=True):
                path, count, _ = append_training_feedback_to_goldset(completed_feedback, split=training_split)
                st.success(f"Imported {count} rows into {path}")
        except Exception as exc:
            st.error(f"Could not import client feedback: {exc}")

    st.markdown("**Quick field guide**")
    st.write(
        "- `Send as is`: the client would send the line without changes.\n"
        "- `Rewrite`: the idea might be usable, but the client wants different wording. The rewrite is the most valuable training signal.\n"
        "- `Reject`: the line should not be used. Pick the closest reason so the system can learn what failed.\n"
        "- `Surface to focus on`: where the observation should come from, such as app onboarding, App Store reviews, booking flow, or landing page."
    )

    st.divider()
    st.subheader("Post-send campaign results")
    st.caption("Optional long-term feedback loop. Import open/reply/booked outcomes after a campaign so future calibration can use real performance data.")
    campaign_template_df = st.session_state.get("review_df")
    st.download_button(
        "Download campaign results template",
        campaign_feedback_template_bytes(campaign_template_df),
        "campaign_results_template.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    campaign_feedback = st.file_uploader("Completed campaign results", type=["xlsx", "csv"], key="campaign_results_upload")
    if campaign_feedback is not None:
        try:
            raw_campaign = read_campaign_feedback(campaign_feedback)
            normalized_campaign = normalize_campaign_feedback(raw_campaign)
            if normalized_campaign.empty:
                st.warning("No rows with campaign outcome signals were found.")
            else:
                st.dataframe(normalized_campaign, use_container_width=True, height=260)
            if st.button("Import campaign results", use_container_width=True):
                path, count, _ = append_campaign_feedback(campaign_feedback)
                st.success(f"Imported {count} campaign result rows into {path}")
        except Exception as exc:
            st.error(f"Could not import campaign results: {exc}")
    existing_campaign = load_campaign_feedback(limit=25)
    if not existing_campaign.empty:
        with st.expander("Recent imported campaign results"):
            st.dataframe(existing_campaign, use_container_width=True, height=240)
