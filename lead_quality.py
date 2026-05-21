from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from email_verification import EmailVerificationResult, email_from_original_columns
from input_loader import dedupe_key
from models import LeadInput


@dataclass
class LeadQualityResult:
    lead_quality_score: int
    lead_quality_flags: list[str]
    missing_required_fields: list[str]
    duplicate_company: bool
    duplicate_contact: bool
    app_link_status: str
    ready_for_personalization: bool
    lead_quality_notes: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lead_quality_flags"] = " | ".join(self.lead_quality_flags)
        payload["missing_required_fields"] = " | ".join(self.missing_required_fields)
        payload["duplicate_company"] = "yes" if self.duplicate_company else "no"
        payload["duplicate_contact"] = "yes" if self.duplicate_contact else "no"
        payload["ready_for_personalization"] = "yes" if self.ready_for_personalization else "no"
        return payload


@dataclass
class LeadQualityContext:
    company_counts: Counter[str]
    contact_counts: Counter[str]


def build_lead_quality_context(leads: list[LeadInput]) -> LeadQualityContext:
    company_counts: Counter[str] = Counter()
    contact_counts: Counter[str] = Counter()
    for lead in leads:
        try:
            company_counts[dedupe_key(lead)] += 1
        except Exception:
            company_counts[str(lead.company_name or "").strip().lower()] += 1
        email = email_from_original_columns(lead.original_columns).lower()
        contact_key = email or f"{lead.recipient_name}|{lead.company_name}".lower()
        if contact_key.strip("|"):
            contact_counts[contact_key] += 1
    return LeadQualityContext(company_counts=company_counts, contact_counts=contact_counts)


def _app_link_status(lead: LeadInput) -> str:
    app_url = str(lead.app_store_url or "").strip()
    if not app_url:
        return "not_provided"
    parsed = urlparse(app_url if app_url.startswith(("http://", "https://")) else f"https://{app_url}")
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "provided"
    return "invalid_or_unclear"


def evaluate_lead_quality(
    lead: LeadInput,
    context: LeadQualityContext | None = None,
    email_verification: EmailVerificationResult | None = None,
) -> LeadQualityResult:
    missing: list[str] = []
    flags: list[str] = []
    score = 100

    if not str(lead.company_name or "").strip():
        missing.append("company_name")
        score -= 30
    if not str(lead.website_url or "").strip():
        missing.append("website_url")
        score -= 35
    if not str(lead.recipient_name or "").strip():
        flags.append("missing_recipient_name")
        score -= 8
    if not str(lead.recipient_role or "").strip():
        flags.append("missing_recipient_role")
        score -= 6
    if lead.validation_errors:
        flags.extend(lead.validation_errors)
        score -= min(35, 12 * len(lead.validation_errors))

    duplicate_company = bool(lead.is_duplicate)
    duplicate_contact = False
    if context:
        try:
            duplicate_company = context.company_counts.get(dedupe_key(lead), 0) > 1
        except Exception:
            duplicate_company = context.company_counts.get(str(lead.company_name or "").strip().lower(), 0) > 1
        email = email_from_original_columns(lead.original_columns).lower()
        contact_key = email or f"{lead.recipient_name}|{lead.company_name}".lower()
        duplicate_contact = bool(contact_key.strip("|") and context.contact_counts.get(contact_key, 0) > 1)
    if duplicate_company:
        flags.append("duplicate_company")
        score -= 8
    if duplicate_contact:
        flags.append("duplicate_contact")
        score -= 12

    app_status = _app_link_status(lead)
    if app_status == "invalid_or_unclear":
        flags.append("app_link_invalid_or_unclear")
        score -= 8

    if email_verification:
        if email_verification.status == "invalid":
            flags.append("email_invalid")
            score -= 30
        elif email_verification.status == "risky":
            flags.append("email_risky")
            score -= 15
        elif email_verification.status == "not_checked":
            flags.append("email_not_checked")
        elif email_verification.status == "unknown":
            flags.append("email_unknown")
            score -= 5

    score = max(0, min(100, score))
    ready = score >= 60 and "website_url" not in missing and "company_name" not in missing
    if not ready:
        flags.append("lead_quality_needs_review")
    notes = "Batch continues; weak leads are flagged for stricter review." if flags else "Lead has enough basic data for personalization."
    return LeadQualityResult(
        lead_quality_score=score,
        lead_quality_flags=list(dict.fromkeys(flags)),
        missing_required_fields=missing,
        duplicate_company=duplicate_company,
        duplicate_contact=duplicate_contact,
        app_link_status=app_status,
        ready_for_personalization=ready,
        lead_quality_notes=notes,
    )
