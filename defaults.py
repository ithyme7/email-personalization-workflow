from models import LeadInput

# Original universal fallback — kept for edge cases where even role/company are missing
PITCH_SENTENCE = "We help mobile app teams with this type of work, figure out where users drop off and why."


def _default_next_sentence(lead: LeadInput) -> str:
    """Generate a per-lead contextual next sentence when campaign_context is empty.

    Instead of the same generic fallback for every lead, this crafts a minimally
    personalized sentence using company name and/or recipient role so no two
    emails read identically when the spreadsheet leaves campaign_context blank.
    """
    company = (lead.company_name or "").strip()
    role = (lead.recipient_role or "").strip()

    if company and role:
        return (
            f"Curious where {company} is seeing the biggest drop-off from a "
            f"{role} perspective."
        )
    if company:
        return f"Curious what's top of mind at {company} when it comes to user drop-off and conversion."
    if role:
        return "Curious where teams are seeing the biggest friction or drop-off for users right now."
    return PITCH_SENTENCE