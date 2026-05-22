from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_client import load_prompt_pair, render_prompt_template
from models import EvidenceFact, EvidenceResult, LeadInput, PersonalizationDraft
from personalization_writer import _render_user_payload, write_personalization
from sequence_engine import _build_user_payload


def _evidence() -> EvidenceResult:
    return EvidenceResult(
        facts=[
            EvidenceFact(
                fact="The App Store reviews mention signup confusion.",
                why_it_matters="That could hurt activation.",
                source_url="https://apps.apple.com/example",
                strength="strong",
                too_generic_to_use=False,
                friction_type="signup_friction",
                surface_checked="app listing",
                conversion_outcome="activation",
            )
        ]
    )


def test_brace_prompt_renderer_replaces_known_placeholders_and_keeps_json_examples() -> None:
    rendered = render_prompt_template(
        "Company: {company_name}\nReturn JSON: {\"opening_line\": \"...\"}\nUnknown: {unknown_key}",
        {"company_name": "Little Otter"},
    )
    assert "Company: Little Otter" in rendered
    assert '{"opening_line": "..."}' in rendered
    assert "{unknown_key}" in rendered


def test_write_prompt_no_longer_leaks_lead_placeholders() -> None:
    lead = LeadInput(
        company_name="Trayt Health",
        website_url="https://trayt.health",
        recipient_name="Malekeh Amini",
        recipient_role="Founder & CEO",
        app_flow_observation="the public app listing mentions access friction",
    )
    rendered = _render_user_payload(
        lead=lead,
        evidence=_evidence(),
        tone_profile=None,
        required_next_sentence="We help mobile app teams understand where users drop off and why.",
        variant_index=1,
        avoid_opening_lines=[],
        variant_instruction="Use the strongest app-store angle.",
    )
    assert "Company: Trayt Health" in rendered
    assert "{company_name}" not in rendered
    assert "{app_flow_observation}" not in rendered
    assert "{required_next_sentence}" not in rendered
    assert "{opening_line}" not in rendered


def test_write_system_prompt_no_longer_leaks_template_placeholders() -> None:
    system_template, _ = load_prompt_pair("write_personalization")
    rendered = render_prompt_template(
        system_template,
        {
            "opening_line": "[personalized opening line]",
            "required_next_sentence": "We help mobile app teams understand where users drop off and why.",
        },
    )
    assert "{opening_line}" not in rendered
    assert "{required_next_sentence}" not in rendered


def test_writer_sends_rendered_system_prompt_to_client() -> None:
    class FakeClient:
        system_text = ""

        def complete_json(self, system: str, user: str, temperature: float = 0.0) -> dict:
            self.system_text = system
            return {
                "opening_line": "I was checking the trayt health app listing and saw access friction, which could slow activation.",
                "tailored_insight": "The line stays grounded in public app evidence.",
                "chosen_angle": "app_access_friction",
                "evidence_used_for_copy": ["Public app listing mentions access friction."],
            }

    client = FakeClient()
    write_personalization(
        client=client,  # type: ignore[arg-type]
        lead=LeadInput(company_name="Trayt Health", website_url="https://trayt.health"),
        evidence=_evidence(),
        temperature=0.0,
    )
    assert "{opening_line}" not in client.system_text
    assert "{required_next_sentence}" not in client.system_text


def test_qc_prompt_template_can_render_brace_placeholders() -> None:
    _, template = load_prompt_pair("qc_personalization")
    rendered = render_prompt_template(
        template,
        {
            "company_name": "Behavioral Health Tech",
            "website_url": "https://behavioralhealthtech.com",
            "recipient_name": "Solome Tibebu",
            "recipient_role": "Founder",
            "campaign_context": "We help mobile app teams understand drop-off.",
            "linkedin_observation": "",
            "app_flow_observation": "",
            "recent_news_note": "",
            "competitor_context": "",
            "opening_line": "I was checking the event site and the registration CTA sits below the first screen, which could cost signups.",
            "required_next_sentence": "We help mobile app teams understand where users drop off and why.",
            "evidence_text": "CTA below first viewport.",
            "draft_opening_line": "I was checking the event site and the registration CTA sits below the first screen, which could cost signups.",
            "draft_tailored_insight": "",
            "draft_chosen_angle": "low_visibility_cta",
            "draft_evidence_used": "[\"CTA below first viewport.\"]",
            "tone_profile_text": "{}",
            "feedback_context": "",
            "research_depth": 0.8,
        },
    )
    assert "Company: Behavioral Health Tech" in rendered
    assert "{company_name}" not in rendered
    assert "{draft_opening_line}" not in rendered
    assert "{opening_line}" not in rendered


def test_followup_prompt_no_longer_leaks_sequence_placeholders() -> None:
    lead = LeadInput(company_name="Rootd", website_url="https://rootd.io")
    draft = PersonalizationDraft(
        opening_line="I was checking the rootd App Store reviews and saw trial-charge complaints, which could hurt paywall conversion.",
        chosen_angle="app_review: paywall friction",
        evidence_used_for_copy=["Trial-charge complaints in public reviews."],
    )
    rendered = _build_user_payload(
        lead=lead,
        original_draft=draft,
        step_number=1,
        tone_profile=None,
        all_evidence_texts=["Support complaints in public reviews."],
    )
    assert "Original email angle: app_review: paywall friction" in rendered
    assert "{original_angle}" not in rendered
    assert "{step_number}" not in rendered
    assert "{remaining_evidence_text}" not in rendered
