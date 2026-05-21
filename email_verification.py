from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass
class EmailVerificationResult:
    email: str = ""
    status: str = "not_checked"
    provider: str = "noop"
    confidence: int = 0
    reason: str = "No email verification provider configured."
    checked_at: str = ""

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


class EmailVerifier(Protocol):
    provider: str

    def verify(self, email: str) -> EmailVerificationResult:
        ...


class NoOpEmailVerifier:
    provider = "noop"

    def verify(self, email: str) -> EmailVerificationResult:
        return EmailVerificationResult(
            email=str(email or "").strip(),
            status="not_checked",
            provider=self.provider,
            confidence=0,
            reason="No provider configured; batch was not blocked.",
            checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


EMAIL_COLUMN_CANDIDATES = (
    "email",
    "Email",
    "Contact Email",
    "Work Email",
    "Person Email",
    "recipient_email",
)


def email_from_original_columns(original_columns: dict[str, str]) -> str:
    lowered = {str(key).strip().lower(): str(value or "").strip() for key, value in original_columns.items()}
    for candidate in EMAIL_COLUMN_CANDIDATES:
        value = lowered.get(candidate.lower(), "")
        if value:
            return value
    return ""


def verify_lead_email(original_columns: dict[str, str], verifier: EmailVerifier | None = None) -> EmailVerificationResult:
    active_verifier = verifier or NoOpEmailVerifier()
    return active_verifier.verify(email_from_original_columns(original_columns))
