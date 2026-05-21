from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_verification import NoOpEmailVerifier, verify_lead_email
from lead_quality import build_lead_quality_context, evaluate_lead_quality
from models import LeadInput, PageText, ResearchResult
from research_tasks import (
    company_latest_funding_details,
    detect_revenue_model,
    detect_target_customer,
    website_tech_stack,
    website_traffic_tracker,
)


def _research(text: str) -> ResearchResult:
    return ResearchResult(
        summary=text,
        pages=[PageText(url="https://example.com", title="Example", text=text)],
        source_urls=["https://example.com"],
    )


def test_revenue_model_returns_structured_output() -> None:
    lead = LeadInput(company_name="Bookly", website_url="https://example.com")
    result = detect_revenue_model(lead, _research("Book appointments, reserve classes, and manage subscriptions."))
    assert result.result in {"pay-per-booking", "subscription"}
    assert result.confidence in {"medium", "high"}
    assert isinstance(result.to_dict()["recommended_use_for_opener"], bool)


def test_target_customer_returns_structured_output() -> None:
    lead = LeadInput(company_name="Thera", website_url="https://example.com")
    result = detect_target_customer(lead, _research("Built for therapists and clinic operators."))
    assert result.result == "therapists"
    assert result.confidence == "high"
    assert result.recommended_use_for_opener


def test_low_confidence_funding_and_traffic_are_not_recommended() -> None:
    lead = LeadInput(company_name="Unknown", website_url="https://example.com")
    research = _research("Plain homepage copy.")
    funding = company_latest_funding_details(lead, research)
    traffic = website_traffic_tracker(lead, research)
    assert funding.confidence == "low"
    assert not funding.recommended_use_for_opener
    assert traffic.result == "not available"
    assert traffic.confidence == "low"
    assert not traffic.recommended_use_for_opener


def test_tech_stack_detection_fails_safely() -> None:
    lead = LeadInput(company_name="NoHtml", website_url="https://example.com")
    result = website_tech_stack(lead, _research(""), html="")
    assert result.result == "unclear"
    assert result.confidence == "low"
    assert not result.recommended_use_for_opener


def test_tech_stack_detection_uses_light_html_signals() -> None:
    lead = LeadInput(company_name="Shop", website_url="https://example.com")
    html = '<html><script src="https://cdn.shopify.com/theme.js"></script><script src="/_next/static/app.js"></script></html>'
    result = website_tech_stack(lead, _research(""), html=html)
    assert "Shopify" in result.result
    assert result.confidence == "high"
    assert not result.recommended_use_for_opener


def test_noop_email_verifier_returns_not_checked() -> None:
    result = verify_lead_email({"Email": "jane@example.com"}, NoOpEmailVerifier())
    assert result.email == "jane@example.com"
    assert result.status == "not_checked"


def test_lead_quality_score_reacts_to_missing_and_duplicates() -> None:
    leads = [
        LeadInput(company_name="Acme", website_url="https://example.com", original_columns={"Email": "a@example.com"}),
        LeadInput(company_name="Acme", website_url="https://example.com", original_columns={"Email": "a@example.com"}),
        LeadInput(company_name="", website_url="", original_columns={}),
    ]
    context = build_lead_quality_context(leads)
    duplicate = evaluate_lead_quality(leads[0], context)
    missing = evaluate_lead_quality(leads[2], context)
    assert duplicate.duplicate_company
    assert duplicate.duplicate_contact
    assert "company_name" in missing.missing_required_fields
    assert missing.lead_quality_score < duplicate.lead_quality_score


if __name__ == "__main__":
    test_revenue_model_returns_structured_output()
    test_target_customer_returns_structured_output()
    test_low_confidence_funding_and_traffic_are_not_recommended()
    test_tech_stack_detection_fails_safely()
    test_tech_stack_detection_uses_light_html_signals()
    test_noop_email_verifier_returns_not_checked()
    test_lead_quality_score_reacts_to_missing_and_duplicates()
    print("enrichment_lead_quality_tests_ok")
