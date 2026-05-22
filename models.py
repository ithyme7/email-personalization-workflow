from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


OUTPUT_COLUMNS = [
    "row_id",
    "run_id",
    "example_id",
    "company_name",
    "website_url",
    "linkedin_url",
    "recipient_name",
    "recipient_role",
    "campaign_context",
    "tone_profile",
    "model_provider",
    "model_name",
    "prompt_set_hash",
    "evidence_prompt_hash",
    "write_prompt_hash",
    "qc_prompt_hash",
    "tone_profile_hash",
    "llm_calls",
    "estimated_input_tokens",
    "estimated_output_tokens",
    "estimated_model_cost_usd",
    "linkedin_observation",
    "linkedin_source_note",
    "app_store_url",
    "app_store_summary",
    "app_review_themes",
    "app_flow_observation",
    "app_flow_source_note",
    "screenshot_url",
    "recent_news_url",
    "recent_news_note",
"competitor_context",
    "research_depth",
    "friction_checklist",
    "app_check_status",
    "recommended_manual_check",
    "product_surface_type",
    "research_priority",
    "app_review_complaints",
    "template_preview",
    "visual_observations",
    "visual_quality_flags",
    "visual_confidence",
    "visual_confidence_score",
    "visual_confidence_reasons",
    "screenshot_paths",
    "shareable_screenshot_files",
    "trace_files",
    "advanced_detector_flags",
    "ux_validator_findings",
    "dead_link_checks",
    "friction_type",
    "surface_checked",
    "conversion_outcome",
    "angle_gate_decision",
    "angle_gate_notes",
    "blocked_angles",
    "angle_priority",
    "blog_used",
    "why_this_angle",
    "raw_research_summary",
    "evidence_points",
    "evidence_used_for_copy",
    "chosen_angle",
    "opening_line",
    "tailored_insight",
    "opening_line_option_1",
    "tailored_insight_option_1",
    "chosen_angle_option_1",
    "evidence_used_for_copy_option_1",
    "confidence_score_option_1",
    "quality_flags_option_1",
    "needs_manual_review_option_1",
    "reviewer_notes_option_1",
    "template_preview_option_1",
    "opening_line_option_2",
    "tailored_insight_option_2",
    "chosen_angle_option_2",
    "evidence_used_for_copy_option_2",
    "confidence_score_option_2",
    "quality_flags_option_2",
    "needs_manual_review_option_2",
    "reviewer_notes_option_2",
    "template_preview_option_2",
    "opening_line_option_3",
    "tailored_insight_option_3",
    "chosen_angle_option_3",
    "evidence_used_for_copy_option_3",
    "confidence_score_option_3",
    "quality_flags_option_3",
    "needs_manual_review_option_3",
    "reviewer_notes_option_3",
    "template_preview_option_3",
    "confidence_score",
    "evidence_strength_score",
    "personalization_quality_score",
    "send_confidence",
    "quality_flags",
    "source_urls",
"needs_manual_review",
    "reviewer_notes",
    # --- Sequence columns ---
    "sequence_step",
    "follow_up_type",
    "sequence_opening_line",
    "sequence_body_text",
    "sequence_cta_text",
    "sequence_chosen_angle",
    "sequence_evidence_used",
    "sequence_quality_score",
    "sequence_quality_flags",
    "sequence_needs_review",
    # --- A/B Test columns ---
    "ab_experiment_id",
    "ab_variant_id",
    "ab_variant_label",
    "ab_testing_enabled",
]


@dataclass
class LeadInput:
    company_name: str
    website_url: str
    linkedin_url: str = ""
    recipient_name: str = ""
    recipient_role: str = ""
    campaign_context: str = ""
    optional_notes: str = ""
    linkedin_observation: str = ""
    linkedin_source_note: str = ""
    app_store_url: str = ""
    app_flow_observation: str = ""
    app_flow_source_note: str = ""
    screenshot_url: str = ""
    recent_news_url: str = ""
    recent_news_note: str = ""
    competitor_context: str = ""
    is_valid: bool = True
    validation_errors: list[str] = field(default_factory=list)
    is_duplicate: bool = False
    original_columns: dict[str, str] = field(default_factory=dict)
    research_depth: float = 1.0


@dataclass
class ToneProfile:
    name: str
    description: str = ""
    opening_style: str = ""
    custom_prompt: str = ""
    angle_priorities: list[str] = field(default_factory=list)
    preferred_phrases: list[str] = field(default_factory=list)
    banned_phrases: list[str] = field(default_factory=list)
    qc_focus: list[str] = field(default_factory=list)
    example_good_lines: list[str] = field(default_factory=list)
    example_bad_lines: list[str] = field(default_factory=list)

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "opening_style": self.opening_style,
            "custom_prompt": self.custom_prompt,
            "angle_priorities": self.angle_priorities,
            "preferred_phrases": self.preferred_phrases,
            "banned_phrases": self.banned_phrases,
            "qc_focus": self.qc_focus,
            "example_good_lines": self.example_good_lines,
            "example_bad_lines": self.example_bad_lines,
        }


@dataclass
class DeepResearchResult:
    app_store_url: str = ""
    app_store_summary: str = ""
    app_review_themes: list[str] = field(default_factory=list)
    linkedin_observation: str = ""
    linkedin_source_note: str = ""
    app_flow_observation: str = ""
    app_flow_source_note: str = ""
    screenshot_url: str = ""
    recent_news_url: str = ""
    recent_news_note: str = ""
    competitor_context: str = ""
    friction_checklist: list[str] = field(default_factory=list)
    review_complaints: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    reviewer_notes: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        sections = []
        if self.linkedin_observation:
            sections.append(f"LinkedIn observation supplied by reviewer: {self.linkedin_observation}")
        if self.linkedin_source_note:
            sections.append(f"LinkedIn source note: {self.linkedin_source_note}")
        if self.app_store_summary:
            sections.append(f"Public app-store or app listing evidence: {self.app_store_summary}")
        if self.app_review_themes:
            sections.append("Public review theme clusters: " + " | ".join(self.app_review_themes))
        if self.app_flow_observation:
            sections.append(f"Manual app/onboarding observation supplied by reviewer: {self.app_flow_observation}")
        if self.app_flow_source_note:
            sections.append(f"App/onboarding source note: {self.app_flow_source_note}")
        if self.screenshot_url:
            sections.append(f"Screenshot reference supplied by reviewer: {self.screenshot_url}")
        if self.recent_news_note:
            sections.append(f"Recent news or product update note: {self.recent_news_note}")
        if self.recent_news_url:
            sections.append(f"Recent news or product update URL: {self.recent_news_url}")
        if self.competitor_context:
            sections.append(f"Competitor/context note supplied by reviewer: {self.competitor_context}")
        if self.friction_checklist:
            sections.append("Friction checklist: " + " | ".join(self.friction_checklist))
        if self.review_complaints:
            sections.append("Public review complaint signals: " + " | ".join(self.review_complaints))
        return "\n".join(sections)


@dataclass
class PageText:
    url: str
    title: str
    text: str


@dataclass
class ResearchResult:
    summary: str = ""
    pages: list[PageText] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    visual_observations: list[str] = field(default_factory=list)
    visual_quality_flags: list[str] = field(default_factory=list)
    visual_confidence: str = ""
    visual_confidence_score: int = 0
    visual_confidence_reasons: list[str] = field(default_factory=list)
    screenshot_paths: list[str] = field(default_factory=list)
    trace_files: list[str] = field(default_factory=list)
    advanced_detector_flags: list[str] = field(default_factory=list)
    ux_validator_findings: list[str] = field(default_factory=list)
    dead_link_checks: list[str] = field(default_factory=list)
    needs_manual_review: bool = False
    reviewer_notes: list[str] = field(default_factory=list)


@dataclass
class EvidenceFact:
    fact: str
    why_it_matters: str
    source_url: str
    strength: str
    too_generic_to_use: bool
    friction_type: str = ""
    surface_checked: str = ""
    conversion_outcome: str = ""
    angle_priority: int = 0
    blog_used: bool = False
    why_this_angle: str = ""


@dataclass
class EvidenceResult:
    facts: list[EvidenceFact] = field(default_factory=list)
    possible_angles: list[str] = field(default_factory=list)
    needs_manual_review: bool = False
    reviewer_notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AngleSelection:
    selected_fact: EvidenceFact | None = None
    allowed_facts: list[EvidenceFact] = field(default_factory=list)
    blocked_facts: list[str] = field(default_factory=list)
    decision: str = "manual_review"
    quality_flags: list[str] = field(default_factory=list)
    reviewer_notes: list[str] = field(default_factory=list)
    needs_manual_review: bool = True


@dataclass
class PersonalizationDraft:
    opening_line: str = ""
    tailored_insight: str = ""
    chosen_angle: str = ""
    evidence_used_for_copy: list[str] = field(default_factory=list)


@dataclass
class QCResult:
    score: int = 0
    passed: bool = False
    reasons: list[str] = field(default_factory=list)
    suggested_rewrite: dict[str, str] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


def join_list(values: list[str]) -> str:
    return " | ".join([str(value).strip() for value in values if str(value).strip()])
