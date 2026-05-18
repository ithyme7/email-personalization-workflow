from __future__ import annotations

SEVERE_QUALITY_FLAGS = {
    "ai_generation_unavailable",
    "research_failed",
    "evidence_failed",
    "unsupported_claims",
    "unsupported_claim",
    "hallucination",
    "em_dash",
    "invalid_json",
    "html_in_personalization_line",
}

EDIT_QUALITY_FLAGS = {
    "genericness",
    "generic",
    "too_generic",
    "manual_review",
    "weak_evidence",
    "blog_angle_low_value",
    "technical_audit_language",
    "wrong_surface",
    "low_confidence_visual_finding",
    "thin_content",
    "line_not_grounded_in_evidence",
    "evidence_used_not_in_extracted_facts",
    "missing_grounding_evidence",
    "spam_trigger_language",
}

PRIORITY_FRICTION_TYPES = {
    "broken_formatting": 1,
    "low_visibility_cta": 2,
    "unnecessary_clicks": 2,
    "onboarding_friction": 2,
    "signup_friction": 2,
    "hidden_signup_or_login": 2,
    "checkout_friction": 2,
    "weak_testimonial_or_case_study": 3,
    "weak_or_missing_proof": 3,
    "broad_positioning": 4,
    "unclear_value_prop": 4,
    "app_store_signal": 5,
    "other_specific_friction": 6,
}

DISALLOWED_FRICTION_TYPES = {"blog_low_priority"}

OUTCOME_TERMS = {
    "activation",
    "activate",
    "activated",
    "booking",
    "bookings",
    "signup",
    "sign-up",
    "sign up",
    "conversion",
    "convert",
    "converts",
    "converted",
    "drop off",
    "drop-off",
    "dropoff",
    "retention",
    "retain",
    "churn",
    "paywall",
    "subscription",
    "checkout",
    "first session",
    "onboarding",
    "revenue",
    "trial",
    "bouncing",
    "bounce",
}

CONVERSATIONAL_STARTS = (
    "i was checking",
    "i was just checking",
    "i just checked",
    "i checked",
    "i opened",
    "i tried",
    "i clicked",
    "i went through",
    "i was on",
    "i had a look",
)

VISUAL_CLAIM_TERMS = {
    "button",
    "cta",
    "first load",
    "screen",
    "page",
    "mobile",
    "formatting",
    "layout",
    "click",
    "clicked",
    "tap",
    "above the fold",
    "hard to see",
    "easy to miss",
    "broken",
}

APP_SURFACE_TERMS = {
    "app",
    "mobile app",
    "app store",
    "google play",
    "play store",
    "onboarding",
    "signup",
    "sign-up",
    "sign up",
    "paywall",
    "subscription",
    "access code",
    "download",
    "install",
    "first screen",
    "first session",
    "review",
    "rating",
    "screenshots",
}

WEBSITE_SURFACE_TERMS = {
    "website",
    "landing page",
    "homepage",
    "site",
    "page",
    "cta",
    "form",
    "demo",
    "case study",
    "testimonial",
    "proof",
}

BOOKING_TERMS = {"booking", "book", "slot", "availability", "appointment", "reservation", "calendar"}
COMMERCE_TERMS = {"checkout", "cart", "buy", "purchase", "product page", "shipping", "price", "subscription"}
B2B_TERMS = {"demo", "case study", "testimonial", "proof", "roi", "customer", "sales", "lead"}

FRICTION_MARKERS = {
    "access code",
    "below the fold",
    "broken",
    "button",
    "case study",
    "click",
    "cta",
    "confusing",
    "costing",
    "cropped",
    "dead",
    "drop",
    "external",
    "friction",
    "hard to",
    "hidden",
    "horizontal overflow",
    "missing",
    "no clear",
    "not clear",
    "not clickable",
    "paywall",
    "quote",
    "signup",
    "unclear",
    "weak",
    "too many",
    "broad",
    "generic",
    "proof",
    "testimonial",
    "rating reset",
}

HIGH_VALUE_BUG_MARKERS = {
    "404",
    "broken",
    "broken layout",
    "button does not work",
    "button doesn't work",
    "can't click",
    "cannot click",
    "content is cut off",
    "cuts off",
    "dead button",
    "horizontal overflow",
    "layout breaks",
    "not clickable",
    "overlap",
    "overflow",
}

HIGH_VALUE_CTA_MARKERS = {
    "below the fold",
    "blends into",
    "buried",
    "hard to see",
    "hidden",
    "low contrast",
    "no clear cta",
    "no primary cta",
    "primary cta",
    "unclear primary",
}

HIGH_VALUE_FLOW_MARKERS = {
    "access code",
    "before value",
    "booking flow",
    "checkout",
    "first screen",
    "first session",
    "invite code",
    "onboarding",
    "paywall",
    "signup",
    "subscription",
    "too many steps",
    "unnecessary clicks",
}

APP_FIRST_MARKERS = {
    "app store",
    "google play",
    "app listing",
    "public review complaint",
    "review complaint",
    "onboarding",
    "permission",
    "access code",
    "signup requirement",
    "paywall",
    "subscription",
    "first screen",
}

HIGH_VALUE_PROOF_MARKERS = {
    "case study",
    "direct quote",
    "external link",
    "external source",
    "missing proof",
    "no evidence",
    "proof",
    "quote",
    "screenshot",
    "testimonial",
}

BROAD_POSITIONING_MARKERS = {
    "broad positioning",
    "many audiences",
    "multiple audiences",
    "too broad",
    "too many audiences",
    "too many use cases",
    "unclear niche",
}

LOW_PRIORITY_MICRO_UX_MARKERS = {
    "small tap target",
    "small tap targets",
    "tap-target",
    "tap targets",
}

POSITIVE_ONLY_MARKERS = {
    "award-winning",
    "crucial",
    "impressive",
    "innovative",
    "interesting",
    "key to",
    "mission",
    "powerful",
    "unique approach",
    "validation",
}

BANNED_FILLER_WORDS = {"powerful", "impressive", "interesting", "innovative"}

ABSTRACT_PHRASES = {
    "helps users",
    "make it easier",
    "find what they need",
    "better experience",
    "smooth",
    "clearer journey",
    "more seamless",
}

TECHNICAL_AUDIT_TERMS = {
    "contrast ratio",
    "tap target",
    "horizontal overflow",
    "wcag",
    "axe-core",
    "lighthouse",
    "validator",
    "accessibility violation",
}
