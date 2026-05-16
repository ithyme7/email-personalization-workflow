from __future__ import annotations

import re
from urllib.parse import urlparse

from models import DeepResearchResult, LeadInput, ResearchResult


APP_TERMS = {
    "app store",
    "google play",
    "mobile app",
    "ios app",
    "android app",
    "download the app",
    "download on the app store",
    "get it on google play",
    "in-app",
    "onboarding",
}
BOOKING_TERMS = {"book", "booking", "schedule", "appointment", "slot", "reservation"}
COMMERCE_TERMS = {"cart", "checkout", "buy now", "subscribe", "subscription", "paywall", "pricing"}
B2B_TERMS = {"demo", "sales", "case study", "enterprise", "teams", "business", "platform", "solution"}
LEADGEN_TERMS = {"contact", "get started", "request", "consultation", "quote", "call"}


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def classify_surface(lead: LeadInput, research: ResearchResult | None = None, deep: DeepResearchResult | None = None) -> str:
    parts = [
        lead.website_url,
        lead.optional_notes,
        lead.app_store_url,
        lead.app_flow_observation,
    ]
    if research:
        parts.append(research.summary)
        parts.extend(research.source_urls)
    if deep:
        parts.extend([deep.app_store_url, deep.app_store_summary, deep.app_flow_observation])
        parts.extend(deep.friction_checklist)
    text = " ".join(str(part or "") for part in parts).lower()
    domain = urlparse(lead.website_url).netloc.lower()

    if domain.endswith(".app") or lead.app_store_url.strip() or (deep and deep.app_store_url) or _contains_any(text, APP_TERMS):
        return "app_first_product"
    if _contains_any(text, BOOKING_TERMS):
        return "marketplace_booking_flow"
    if _contains_any(text, COMMERCE_TERMS):
        return "commerce_product_page"
    if _contains_any(text, B2B_TERMS):
        return "b2b_service"
    if _contains_any(text, LEADGEN_TERMS):
        return "website_first_leadgen"
    return "website_first_leadgen"


def research_priority_for(surface_type: str) -> str:
    if surface_type == "app_first_product":
        return (
            "App-first priority: App Store/Google Play listing -> screenshots -> public review complaints -> "
            "onboarding permissions -> signup requirement -> paywall/subscription/access-code -> website/landing page."
        )
    if surface_type == "marketplace_booking_flow":
        return "Booking priority: availability visibility -> booking steps -> required account/payment -> CTA clarity -> proof/trust."
    if surface_type == "commerce_product_page":
        return "Commerce priority: product clarity -> CTA visibility -> checkout/subscription friction -> proof -> page formatting."
    if surface_type == "b2b_service":
        return "B2B priority: proof/case studies -> CTA/demo flow -> positioning clarity -> trust evidence -> page formatting."
    return "Leadgen priority: CTA clarity -> form/signup friction -> proof -> positioning clarity -> page formatting."


def is_app_first(surface_type: str) -> bool:
    return surface_type == "app_first_product"
