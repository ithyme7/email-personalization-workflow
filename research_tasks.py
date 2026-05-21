from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

import requests

from config import Settings
from models import LeadInput, ResearchResult


@dataclass
class ResearchTaskResult:
    result: str = "unknown"
    evidence: str = ""
    source_url: str = ""
    confidence: str = "low"
    uncertainty_reason: str = ""
    recommended_use_for_opener: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _combined_research_text(research: ResearchResult) -> str:
    parts = [research.summary]
    for page in research.pages[:4]:
        parts.extend([page.title, page.text[:2500]])
    return " ".join(str(part or "") for part in parts)


def _first_source(research: ResearchResult, lead: LeadInput) -> str:
    return next((url for url in research.source_urls if str(url).strip()), lead.website_url)


def _has_any(text: str, terms: set[str]) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def detect_revenue_model(lead: LeadInput, research: ResearchResult) -> ResearchTaskResult:
    text = _combined_research_text(research)
    patterns = [
        ("marketplace", {"marketplace", "providers", "customers book", "find professionals"}),
        ("pay-per-booking", {"book a", "booking", "appointments", "reserve", "classes"}),
        ("subscription", {"subscription", "subscribe", "monthly", "annual plan", "pricing plan"}),
        ("ecommerce", {"cart", "checkout", "shopify", "add to cart", "online store"}),
        ("B2B SaaS", {"software for", "platform for teams", "request a demo", "book a demo", "saas"}),
        ("lead generation", {"get a quote", "contact sales", "free consultation", "request quote"}),
        ("service business", {"services", "agency", "consulting", "done for you"}),
    ]
    matches = [(label, terms) for label, terms in patterns if _has_any(text, terms)]
    if not matches:
        return ResearchTaskResult(
            result="unclear",
            source_url=_first_source(research, lead),
            confidence="low",
            uncertainty_reason="No clear pricing, booking, marketplace, ecommerce, or demo language found.",
            recommended_use_for_opener=False,
        )
    label, terms = matches[0]
    evidence_terms = [term for term in terms if term in text.lower()]
    confidence = "high" if len(evidence_terms) >= 2 else "medium"
    return ResearchTaskResult(
        result=label,
        evidence=", ".join(evidence_terms[:4]) or label,
        source_url=_first_source(research, lead),
        confidence=confidence,
        uncertainty_reason="" if confidence == "high" else "Revenue model inferred from limited page language.",
        recommended_use_for_opener=confidence in {"medium", "high"} and label in {"marketplace", "pay-per-booking", "subscription", "B2B SaaS"},
    )


def detect_target_customer(lead: LeadInput, research: ResearchResult) -> ResearchTaskResult:
    text = _combined_research_text(research)
    lower = text.lower()
    known_targets = [
        "therapists",
        "employers",
        "hr teams",
        "personal trainers",
        "parents",
        "clinic operators",
        "consumers with anxiety",
        "app-first consumer users",
        "founders",
        "sales teams",
        "marketing teams",
        "developers",
    ]
    for target in known_targets:
        if target in lower:
            return ResearchTaskResult(
                result=target,
                evidence=target,
                source_url=_first_source(research, lead),
                confidence="high",
                recommended_use_for_opener=True,
            )
    match = re.search(r"\b(?:for|built for|made for|helps)\s+([a-z][a-z0-9 /&-]{4,60})", lower)
    if match:
        target = " ".join(match.group(1).split())[:80]
        return ResearchTaskResult(
            result=target,
            evidence=match.group(0)[:120],
            source_url=_first_source(research, lead),
            confidence="medium",
            uncertainty_reason="Target inferred from website phrase.",
            recommended_use_for_opener=True,
        )
    return ResearchTaskResult(
        result="unclear",
        source_url=_first_source(research, lead),
        confidence="low",
        uncertainty_reason="No explicit target customer phrase found.",
        recommended_use_for_opener=False,
    )


def website_tech_stack(
    lead: LeadInput,
    research: ResearchResult,
    settings: Settings | None = None,
    html: str = "",
) -> ResearchTaskResult:
    source_url = _first_source(research, lead)
    page_html = html
    if not page_html and settings:
        try:
            response = requests.get(
                lead.website_url,
                headers={"User-Agent": settings.browser_user_agent or "Mozilla/5.0"},
                timeout=min(settings.request_timeout_seconds, 10),
            )
            if response.status_code < 400:
                page_html = response.text[:250000]
        except requests.RequestException:
            page_html = ""
    lower = page_html.lower()
    if not lower:
        return ResearchTaskResult(
            result="unclear",
            source_url=source_url,
            confidence="low",
            evidence="",
            uncertainty_reason="HTML was unavailable; tech stack detection skipped safely.",
            recommended_use_for_opener=False,
        )
    signals = []
    checks = [
        ("Shopify", ("cdn.shopify.com", "shopify")),
        ("Webflow", ("webflow.js", "webflow.com")),
        ("WordPress", ("wp-content", "wp-json", "wordpress")),
        ("React/Next.js hints", ("__next", "next/static", "react")),
        ("Google Analytics", ("gtag(", "google-analytics.com", "googletagmanager.com")),
        ("Segment", ("segment.com/analytics", "cdn.segment.com")),
        ("Hotjar", ("hotjar", "static.hotjar.com")),
    ]
    for label, markers in checks:
        if any(marker in lower for marker in markers):
            signals.append(label)
    if not signals:
        return ResearchTaskResult(
            result="unclear",
            source_url=source_url,
            confidence="low",
            uncertainty_reason="No common CMS, frontend, or analytics markers found.",
            recommended_use_for_opener=False,
        )
    confidence = "high" if len(signals) >= 2 else "medium"
    return ResearchTaskResult(
        result=", ".join(signals),
        evidence=", ".join(signals),
        source_url=source_url,
        confidence=confidence,
        uncertainty_reason="Lightweight HTML marker detection only.",
        recommended_use_for_opener=False,
    )


def company_latest_funding_details(lead: LeadInput, research: ResearchResult) -> ResearchTaskResult:
    funding_columns = [
        "Last Funding Amount",
        "Approx USD Equivalent",
        "Funding",
        "Latest Funding",
        "Funding Stage",
    ]
    evidence_parts = [
        f"{column}: {lead.original_columns.get(column, '')}"
        for column in funding_columns
        if str(lead.original_columns.get(column, "")).strip()
    ]
    news_note = str(lead.recent_news_note or "").strip()
    news_url = str(lead.recent_news_url or "").strip()
    if news_note and re.search(r"\b(raised|funding|series|seed|investment)\b", news_note, flags=re.IGNORECASE) and news_url:
        return ResearchTaskResult(
            result=news_note[:220],
            evidence=news_note[:220],
            source_url=news_url,
            confidence="high",
            recommended_use_for_opener=True,
        )
    if evidence_parts:
        return ResearchTaskResult(
            result="; ".join(evidence_parts)[:220],
            evidence="; ".join(evidence_parts)[:220],
            source_url=news_url,
            confidence="medium" if news_url else "low",
            uncertainty_reason="Funding-like input was supplied but source URL is missing." if not news_url else "",
            recommended_use_for_opener=bool(news_url),
        )
    return ResearchTaskResult(
        result="unknown",
        confidence="low",
        uncertainty_reason="No reliable funding or company-news source available.",
        recommended_use_for_opener=False,
    )


def website_traffic_tracker(lead: LeadInput, research: ResearchResult) -> ResearchTaskResult:
    return ResearchTaskResult(
        result="not available",
        source_url="",
        confidence="low",
        uncertainty_reason="No traffic provider/API configured. Similarweb, Ahrefs, SEMrush or another provider can be added later.",
        recommended_use_for_opener=False,
    )


def run_research_tasks(lead: LeadInput, research: ResearchResult, settings: Settings | None = None) -> dict[str, Any]:
    revenue = detect_revenue_model(lead, research)
    target = detect_target_customer(lead, research)
    tech_stack = website_tech_stack(lead, research, settings=settings)
    funding = company_latest_funding_details(lead, research)
    traffic = website_traffic_tracker(lead, research)
    return {
        "research_revenue_model": revenue.result,
        "research_revenue_model_confidence": revenue.confidence,
        "research_revenue_model_evidence": revenue.evidence,
        "research_revenue_model_source_url": revenue.source_url,
        "research_target_customer": target.result,
        "research_target_customer_confidence": target.confidence,
        "research_target_customer_evidence": target.evidence,
        "research_target_customer_source_url": target.source_url,
        "research_website_tech_stack": tech_stack.result,
        "research_website_tech_stack_confidence": tech_stack.confidence,
        "research_website_tech_stack_evidence": tech_stack.evidence,
        "research_latest_funding_details": funding.result,
        "research_latest_funding_confidence": funding.confidence,
        "research_latest_funding_source_url": funding.source_url,
        "research_traffic_summary": traffic.result,
        "research_traffic_confidence": traffic.confidence,
        "research_traffic_source": traffic.source_url,
        "_research_task_results": {
            "detect_revenue_model": revenue.to_dict(),
            "detect_target_customer": target.to_dict(),
            "website_tech_stack": tech_stack.to_dict(),
            "company_latest_funding_details": funding.to_dict(),
            "website_traffic_tracker": traffic.to_dict(),
        },
    }


def recommended_research_context(fields: dict[str, Any]) -> str:
    task_results = fields.get("_research_task_results", {})
    parts: list[str] = []
    for name, payload in task_results.items():
        confidence = str(payload.get("confidence", "low")).lower()
        if confidence not in {"medium", "high"} or not payload.get("recommended_use_for_opener"):
            continue
        result = str(payload.get("result", "")).strip()
        evidence = str(payload.get("evidence", "")).strip()
        source = str(payload.get("source_url", "")).strip()
        if result:
            parts.append(f"{name}: {result}. Evidence: {evidence}. Source: {source}. Confidence: {confidence}.")
    return " ".join(parts)
