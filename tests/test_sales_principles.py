from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sales_principles import evaluate_sales_principles
from sendability import evaluate_sendability


EVIDENCE = (
    "The App Store reviews mention login confusion and a paywall before users understand the first exercise. "
    "Several users say signup access is unclear."
)


def test_generic_clever_opener_scores_low() -> None:
    result = evaluate_sales_principles(
        "Love what you're doing with such an innovative product.",
        evidence=EVIDENCE,
        source_url="https://example.com",
    )
    assert result.specificity_score < 60
    assert result.sales_principles_score < 75


def test_fake_familiarity_is_flagged() -> None:
    result = evaluate_sales_principles(
        "I downloaded the app and loved using it, but the paywall could hurt activation.",
        evidence=EVIDENCE,
        source_url="https://example.com",
        manual_app_verified=False,
    )
    assert result.fake_familiarity_flag
    sendability = evaluate_sendability(
        {
            "personalized_line": "I downloaded the app and loved using it, but the paywall could hurt activation.",
            "evidence_found": EVIDENCE,
            "source_urls": "https://example.com",
        }
    )
    assert sendability["sendability_decision"] == "Reject"
    assert "fake_familiarity_claim" in sendability["hard_fail_reasons"]


def test_missing_outcome_bridge_is_downscored() -> None:
    result = evaluate_sales_principles(
        "I was checking the app listing and noticed the login wording is unclear.",
        evidence=EVIDENCE,
        source_url="https://example.com",
    )
    assert result.outcome_bridge_score < 60
    assert "missing_natural_bridge_to_pitch_outcome" in result.sales_principles_reasons


def test_specific_friction_beats_generic_praise() -> None:
    strong = evaluate_sales_principles(
        "I was checking the app listing and the repeated login complaints look like a place where new users could drop off before activation.",
        evidence=EVIDENCE,
        source_url="https://example.com",
        angle="login/signup/access friction",
    )
    weak = evaluate_sales_principles(
        "Your app has a really cool approach that caught my eye.",
        evidence=EVIDENCE,
        source_url="https://example.com",
    )
    assert strong.sales_principles_score > weak.sales_principles_score
    assert strong.friction_relevance_score > weak.friction_relevance_score


def test_salesy_hype_is_flagged() -> None:
    result = evaluate_sales_principles(
        "I was checking the app listing and saw a revolutionary chance to supercharge conversion.",
        evidence=EVIDENCE,
        source_url="https://example.com",
    )
    assert result.salesy_language_flag


def test_unsupported_claim_creates_hard_fail() -> None:
    sendability = evaluate_sendability(
        {
            "personalized_line": "I was checking the app listing and saw traffic doubled after the new paywall, which could lift conversion.",
            "evidence_found": "The listing mentions a paywall.",
            "source_urls": "https://example.com",
        }
    )
    assert sendability["sendability_decision"] == "Reject"
    assert "unsupported_meaningful_claim" in sendability["hard_fail_reasons"]


def test_signal_only_opener_gets_downscored() -> None:
    result = evaluate_sales_principles(
        "Saw you are hiring SDRs.",
        evidence="Careers page lists SDR openings.",
        source_url="https://example.com/careers",
    )
    assert result.signal_to_implication_bridge_score < 55
    assert "signal_only_no_implication_bridge" in result.sales_principles_reasons


def test_signal_implication_tension_scores_higher() -> None:
    weak = evaluate_sales_principles(
        "Saw you are hiring SDRs.",
        evidence="Careers page lists SDR openings.",
        source_url="https://example.com/careers",
    )
    strong = evaluate_sales_principles(
        "Saw you are hiring SDRs. Usually that means the team is trying to increase outbound volume without letting quality collapse.",
        evidence="Careers page lists SDR openings.",
        source_url="https://example.com/careers",
    )
    assert strong.signal_to_implication_bridge_score > weak.signal_to_implication_bridge_score
    assert strong.sales_principles_score > weak.sales_principles_score


def test_unsupported_implication_is_flagged() -> None:
    result = evaluate_sales_principles(
        "Saw you are hiring SDRs. Usually that means revenue doubled last quarter and outbound volume is exploding.",
        evidence="Careers page lists SDR openings.",
        source_url="https://example.com/careers",
    )
    assert any(reason.startswith("unsupported_implication") for reason in result.sales_principles_reasons)
    assert result.signal_to_implication_bridge_score < 40


if __name__ == "__main__":
    test_generic_clever_opener_scores_low()
    test_fake_familiarity_is_flagged()
    test_missing_outcome_bridge_is_downscored()
    test_specific_friction_beats_generic_praise()
    test_salesy_hype_is_flagged()
    test_unsupported_claim_creates_hard_fail()
    test_signal_only_opener_gets_downscored()
    test_signal_implication_tension_scores_higher()
    test_unsupported_implication_is_flagged()
    print("sales_principles_tests_ok")
