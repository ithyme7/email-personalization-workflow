from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import DATA_DIR
from feedback import load_feedback

SEND_TIME_DB = DATA_DIR / "send_times.sqlite3"

# ============================================================
# Standaard optimale verzendtijden per timezone (UTC)
# Bronnen: Mailchimp, HubSpot, GetResponse research
# ============================================================
DEFAULT_BEST_HOURS: dict[str, list[int]] = {
    # Werkdagen 09:00-11:00 lokale tijd → converteert naar UTC
    "US_Eastern":    [14, 15, 16],       # 09-11 ET = 14-16 UTC
    "US_Central":    [15, 16, 17],       # 09-11 CT = 15-17 UTC
    "US_Mountain":   [16, 17, 18],       # 09-11 MT = 16-18 UTC
    "US_Pacific":    [17, 18, 19],       # 09-11 PT = 17-19 UTC
    "US_Alaska":     [18, 19, 20],       # 09-11 AKST = 18-20 UTC
    "US_Hawaii":     [19, 20, 21],       # 09-11 HST = 19-21 UTC
    "Europe_London": [8, 9, 10],         # 09-11 GMT = 08-10 UTC
    "Europe_Berlin": [7, 8, 9],          # 09-11 CET = 07-09 UTC
    "Europe_Nordic": [7, 8, 9],          # 09-11 CET = 07-09 UTC
    "Asia_Tokyo":    [0, 1, 2],          # 09-11 JST = 00-02 UTC
    "Asia_Singapore": [1, 2, 3],         # 09-11 SGT = 01-03 UTC
    "Asia_Mumbai":   [3, 4, 5],          # 09-11 IST = 03:30-05:30 UTC
    "Australia_Sydney": [23, 0, 1],      # 09-11 AEDT = 23-01 UTC
}

# Fallback: generieke best-practice (dinsdag-donderdag, 10:00-11:00 UTC)
DEFAULT_BEST_HOURS["generic"] = [10, 11, 14, 15]

# Weekdag gewichten (dinsdag = beste dag voor cold email)
WEEKDAY_WEIGHTS = {
    0: 0.65,  # maandag
    1: 0.95,  # dinsdag  ← piek
    2: 0.90,  # woensdag
    3: 0.80,  # donderdag
    4: 0.55,  # vrijdag
    5: 0.25,  # zaterdag
    6: 0.15,  # zondag
}


@dataclass
class SendTimeAdvice:
    """Aanbeveling voor de optimale verzendtijd."""
    send_at_utc: datetime
    timezone_label: str
    confidence: float          # 0.0-1.0 hoe betrouwbaar de aanbeveling is
    source: str                # "historical", "regional_default", "generic_default"
    weekday_factor: float
    hour_score: float
    reasoning: str


def _detect_timezone(region: str) -> str:
    """Bepaal de standaard timezone label op basis van regio."""
    region_lower = region.lower().strip()
    mapping = {
        "us": "US_Eastern",
        "us-east": "US_Eastern",
        "us-central": "US_Central",
        "us-west": "US_Pacific",
        "us-mountain": "US_Mountain",
        "europe": "Europe_Berlin",
        "eu": "Europe_Berlin",
        "uk": "Europe_London",
        "uk-london": "Europe_London",
        "asia-pac": "Asia_Tokyo",
        "asia": "Asia_Tokyo",
        "apac": "Asia_Singapore",
        "australia": "Australia_Sydney",
        "latam": "US_Central",
    }
    for key, tz_label in mapping.items():
        if key in region_lower:
            return tz_label
    return "generic"


def _get_utc_hour_range(tz_label: str) -> list[int]:
    """Haal de optimale UTC-uren op voor een timezone."""
    return DEFAULT_BEST_HOURS.get(tz_label, DEFAULT_BEST_HOURS["generic"])


def _compute_historical_patterns(lead: Any, hours_ahead: int = 24) -> dict[int, float] | None:
    """
    Analyseer historische feedback om patronen te vinden per uur.
    Returns dict: {hour_utc: open_rate} of None als onvoldoende data.
    """
    try:
        feedbacks = load_feedback()
        if len(feedbacks) < 50:
            return None  # Niet genoeg data

        hour_opens: dict[int, list[bool]] = {}
        for fb in feedbacks:
            if not fb.was_opened or not fb.sent_at:
                continue
            try:
                sent_dt = datetime.fromisoformat(fb.sent_at.replace("Z", "+00:00"))
                hour = sent_dt.hour
                hour_opens.setdefault(hour, []).append(fb.was_opened)
            except (ValueError, AttributeError):
                continue

        if not hour_opens:
            return None

        return {
            hour: sum(opens) / len(opens)
            for hour, opens in hour_opens.items()
            if len(opens) >= 3  # Minimaal 3 data points per uur
        }
    except Exception:
        return None


def _pick_best_hour(
    historical: dict[int, float] | None,
    candidate_hours: list[int],
    now_utc: datetime,
    days_ahead: int,
) -> tuple[int, float, str]:
    """Kies het beste uur uit de kandidaten."""
    source = "regional_default"

    if historical:
        scored = []
        for hour in candidate_hours:
            hist_rate = historical.get(hour, 0.0)
            wd = (now_utc.weekday() + days_ahead) % 7
            wd_weight = WEEKDAY_WEIGHTS.get(wd, 0.5)
            score = hist_rate * wd_weight
            scored.append((hour, score))

        if scored:
            scored.sort(key=lambda x: x[1], reverse=True)
            best_hour, best_score = scored[0]
            return best_hour, min(best_score * 1.1, 1.0), "historical"

    # Fallback: eerste uur met beste gewicht
    first_weights = []
    for hour in candidate_hours:
        dt = datetime(now_utc.year, now_utc.month, now_utc.day, hour, tzinfo=timezone.utc)
        wd = (dt.weekday() + days_ahead) % 7
        wd_weight = WEEKDAY_WEIGHTS.get(wd, 0.5)
        # Bonus als het uur al gepasseerd is vandaag → plan voor morgen
        first_weights.append((hour, wd_weight))

    first_weights.sort(key=lambda x: x[1], reverse=True)
    return first_weights[0][0], 0.6, "regional_default"


def compute_send_time(
    lead: Any,
    campaign_context: str = "",
    days_ahead: int = 0,
) -> SendTimeAdvice:
    """
    Bereken de optimale verzendtijd voor een lead.

    Args:
        lead: LeadInput of dict met timezone/region info
        campaign_context: Optionele context voor time-sensitive emails
        days_ahead: Hoeveel dagen in de toekomst (0 = vandaag als nog tijd, 1 = morgen)

    Returns:
        SendTimeAdvice met aanbeveling
    """
    now_utc = datetime.now(timezone.utc)

    # Detecteer timezone
    if hasattr(lead, "campaign_region"):
        region = lead.campaign_region or ""
    elif hasattr(lead, "region"):
        region = lead.region or ""
    elif hasattr(lead, "website_url"):
        # Probeer uit domein te halen (simpele heuristiek)
        region = _guess_region_from_url(getattr(lead, "website_url", ""))
    else:
        region = ""

    tz_label = _detect_timezone(region if region else "generic")
    candidate_hours = _get_utc_hour_range(tz_label)

    # Check historische patronen
    historical = _compute_historical_patterns(lead)

    best_hour, confidence, source = _pick_best_hour(
        historical, candidate_hours, now_utc, days_ahead
    )

    # Bereken de exacte datetime
    target_date = now_utc.date() + timedelta(days=days_ahead)
    send_dt = datetime(target_date.year, target_date.month, target_date.day, best_hour, 0, tzinfo=timezone.utc)

    # Als het al te laat is voor vandaag, schuif naar morgen
    if send_dt <= now_utc + timedelta(hours=1) and days_ahead == 0:
        send_dt += timedelta(days=1)
        days_ahead = 1

    # Weekdag factor voor de uiteindelijke score
    wd = send_dt.weekday()
    wd_factor = WEEKDAY_WEIGHTS.get(wd, 0.5)

    # Confidence aanpassen op basis van data-kwaliteit
    if source == "regional_default":
        final_confidence = round(confidence * wd_factor, 2)
    else:
        final_confidence = round(confidence, 2)

    reasoning_parts = [f"Tijdzone: {tz_label}"]
    if historical:
        reasoning_parts.append("Historische data gebruikt")
    else:
        reasoning_parts.append("Geen historische data → standaard patroon")
    if source == "historical":
        reasoning_parts.append("Data-gedreven uur-selectie")
    else:
        reasoning_parts.append(f"Regio-standaard beste uren: {candidate_hours}")
    reasoning_parts.append(f"Weekdag: {['ma','di','wo','do','vr','za','zo'][wd]} (factor {wd_factor:.2f})")

    return SendTimeAdvice(
        send_at_utc=send_dt,
        timezone_label=tz_label,
        confidence=final_confidence,
        source=source,
        weekday_factor=wd_factor,
        hour_score=confidence,
        reasoning=" | ".join(reasoning_parts),
    )


def _guess_region_from_url(url: str) -> str:
    """Simpel URL-gebaseerde regiodetectie."""
    url_lower = (url or "").lower()
    if ".co.uk" in url_lower or ".uk" in url_lower:
        return "uk"
    if ".de" in url_lower or ".fr" in url_lower or ".nl" in url_lower:
        return "europe"
    if ".jp" in url_lower or ".co.jp" in url_lower:
        return "asia-pac"
    if ".au" in url_lower or ".com.au" in url_lower:
        return "australia"
    if ".ca" in url_lower or ".mx" in url_lower:
        return "latam"
    return "us"


def compare_send_times(lead: Any) -> list[SendTimeAdvice]:
    """
    Geef de top-3 beste verzendtijden voor een lead.
    Handig voor de Streamlit app om keuzes te tonen.
    """
    now_utc = datetime.now(timezone.utc)
    options = []

    for days_ahead in range(4):  # Vandaag + 3 dagen
        advice = compute_send_time(lead, days_ahead=days_ahead)
        advice_with_date = SendTimeAdvice(
            send_at_utc=advice.send_at_utc,
            timezone_label=advice.timezone_label,
            confidence=advice.confidence,
            source=advice.source,
            weekday_factor=advice.weekday_factor,
            hour_score=advice.hour_score,
            reasoning=advice.reasoning,
        )
        options.append(advice_with_date)

    # Sorteer op confidence, beste eerst
    options.sort(key=lambda a: a.confidence, reverse=True)
    return options[:3]


def format_send_time(advice: SendTimeAdvice) -> str:
    """Formatteer de verzendtijd voor weergave."""
    local_label = advice.timezone_label.replace("_", " ")
    return (
        f"{advice.send_at_utc.strftime('%Y-%m-%d %H:%M')} UTC"
        f" ({local_label})"
        f" — confidence: {advice.confidence:.0%}"
    )