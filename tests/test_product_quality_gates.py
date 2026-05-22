from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client_training import EXAMPLE_ROWS
from angle_selector import select_angle
from copy_guardrails import soften_draft_for_weak_evidence
from mismatch_detection import evaluate_mismatch
from models import EvidenceFact, EvidenceResult, PersonalizationDraft
from sendability import evaluate_sendability


def test_app_first_weak_website_surface_gets_review_flag() -> None:
    result = evaluate_sendability(
        {
            "company": "Reflectly",
            "website": "https://reflectlyapp.com",
            "product_surface_type": "app_first_product",
            "personalized_line": "I was checking out the website and noticed the download buttons are hard to read, which could cost app installs.",
            "evidence_found": "App Store reviews mention onboarding and paywall friction.",
            "source_urls": "https://apps.apple.com/us/app/reflectly/id123",
            "app_review_themes": "paywall friction | onboarding confusion",
        }
    )
    assert result["sendability_decision"] == "Edit"
    assert "website_surface_used_for_app_first_product" in result["surface_correctness_reasons"]
    assert "app_review_evidence_preferred" in result["surface_correctness_reasons"]


def test_placeholder_copy_is_never_sendable() -> None:
    result = evaluate_sendability(
        {
            "company": "Trayt Health",
            "website": "https://trayt.health",
            "product_surface_type": "app_first_product",
            "personalized_line": "I opened the {company_name} app and noticed {app_flow_observation}, which could hurt activation.",
            "evidence_found": "The app listing mentions access friction.",
            "source_urls": "https://apps.apple.com/example",
        }
    )
    assert result["sendability_decision"] == "Reject"
    assert "placeholder_token" in result["hard_fail_reasons"]


def test_low_confidence_evidence_softens_assertive_language() -> None:
    draft = PersonalizationDraft(
        opening_line="I bet that's costing signups before users reach activation.",
        evidence_used_for_copy=["Low-confidence visual check suggests signup friction."],
    )
    evidence = EvidenceResult(
        facts=[
            EvidenceFact(
                fact="Low-confidence visual check suggests signup friction.",
                why_it_matters="Could affect activation.",
                source_url="https://example.com",
                strength="weak",
                too_generic_to_use=False,
            )
        ],
        needs_manual_review=True,
    )
    softened = soften_draft_for_weak_evidence(draft, evidence)
    assert "I bet" not in softened.opening_line
    assert "could be costing" in softened.opening_line


def test_low_confidence_evidence_softens_guess_language() -> None:
    draft = PersonalizationDraft(
        opening_line="I'd guess that's costing signups before users reach activation.",
        evidence_used_for_copy=["Low-confidence visual check suggests signup friction."],
    )
    evidence = EvidenceResult(
        facts=[
            EvidenceFact(
                fact="Low-confidence visual check suggests signup friction.",
                why_it_matters="Could affect activation.",
                source_url="https://example.com",
                strength="weak",
                too_generic_to_use=False,
            )
        ],
        needs_manual_review=True,
    )
    softened = soften_draft_for_weak_evidence(draft, evidence)
    assert "I'd guess" not in softened.opening_line
    assert "could be costing" in softened.opening_line


def test_angle_selector_prefers_app_review_surface_for_app_first_products() -> None:
    website_fact = EvidenceFact(
        fact="The homepage CTA is hard to read on mobile.",
        why_it_matters="This could add friction before app installs.",
        source_url="https://example.com",
        strength="strong",
        too_generic_to_use=False,
        friction_type="low_visibility_cta",
        surface_checked="homepage website mobile screenshot",
        conversion_outcome="app installs",
    )
    app_fact = EvidenceFact(
        fact="App Store reviews mention signup confusion before the first exercise.",
        why_it_matters="This could add friction before activation.",
        source_url="https://apps.apple.com/us/app/example/id123",
        strength="medium",
        too_generic_to_use=False,
        friction_type="app_store_signal",
        surface_checked="app listing reviews",
        conversion_outcome="activation",
    )
    selection = select_angle(EvidenceResult(facts=[website_fact, app_fact]))
    assert selection.selected_fact is app_fact
    assert selection.decision == "selected_review_angle"
    assert "app_store_angle_review" in selection.quality_flags


def test_company_domain_mismatch_gets_flagged() -> None:
    result = evaluate_mismatch(
        {
            "company": "Reflectly Pro",
            "website": "https://breathwrk.com",
            "personalized_line": "I was checking the Breathwrk App Store listing and saw paywall complaints.",
            "source_urls": "https://apps.apple.com/us/app/breathwrk/id123",
        }
    )
    assert result["company_website_mismatch"] == "yes"
    assert result["input_mapping_warning"] == "yes"
    assert "company_name_does_not_match_website_domain" in result["mismatch_reason"]


def test_goldset_seed_contains_sdr_bridge_example() -> None:
    matches = [
        row
        for row in EXAMPLE_ROWS
        if row.get("main_reason") == "Signal-to-implication bridge"
        and "hiring SDRs" in row.get("client_rewrite", "")
    ]
    assert matches


if __name__ == "__main__":
    test_app_first_weak_website_surface_gets_review_flag()
    test_low_confidence_evidence_softens_assertive_language()
    test_low_confidence_evidence_softens_guess_language()
    test_angle_selector_prefers_app_review_surface_for_app_first_products()
    test_company_domain_mismatch_gets_flagged()
    test_goldset_seed_contains_sdr_bridge_example()
    print("product_quality_gate_tests_ok")
