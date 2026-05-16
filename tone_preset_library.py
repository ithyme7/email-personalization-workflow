from __future__ import annotations

from models import ToneProfile


COMMON_BANNED = [
    "powerful",
    "impressive",
    "interesting",
    "innovative",
    "game-changing",
    "seamless",
    "I love",
    "I was impressed by",
    "Hope you're well",
]


def _profile(
    name: str,
    description: str,
    surface: str,
    outcome: str,
    priorities: list[str],
    style: str = "Open conversationally as a first-person check of the product, app, website, or landing page.",
) -> ToneProfile:
    return ToneProfile(
        name=name,
        description=description,
        opening_style=style,
        angle_priorities=priorities,
        preferred_phrases=[
            "I was checking out the [product] app...",
            "I opened the [product] app...",
            "I was on the [product] website...",
            "I'd guess...",
            "I bet...",
            "that could be costing...",
        ],
        banned_phrases=COMMON_BANNED,
        qc_focus=[
            f"Prioritize {surface}.",
            f"Tie the line to {outcome}.",
            "Use one surface, one friction point, and one outcome hypothesis.",
            "Flag weak evidence for review instead of making a confident claim.",
            "No em dashes, generic praise, or unsupported claims.",
        ],
        example_good_lines=[
            f"I was checking out the ExampleCo website and noticed the primary action gets buried behind extra context, I'd guess that is costing some users before {outcome}.",
            f"I opened the ExampleCo app and the first screen asks for several decisions before showing value, I bet that creates drop-off around {outcome}.",
        ],
        example_bad_lines=[
            "Your product looks powerful and innovative.",
            "I read your blog and liked the way you explain the market.",
        ],
    )


PRESET_SPECS: list[tuple[str, str, str, str, list[str]]] = [
    ("friction_first", "Default profile for short friction-led openers.", "current UX or conversion friction", "drop-off or conversion", ["Broken formatting", "CTA clarity", "onboarding friction", "weak proof", "broad positioning"]),
    ("proof_led_b2b", "B2B proof, trust, and case-study focused.", "proof gaps and trust leaks", "demo conversion or trust", ["Weak case studies", "missing quotes", "unclear ROI proof", "demo CTA clarity"]),
    ("founder_casual", "Warmer founder-to-founder observations.", "direct product friction", "activation or conversion", ["first action friction", "unclear value", "weak proof", "broad positioning"]),
    ("app_onboarding", "Mobile onboarding and first-session activation.", "app onboarding steps", "first-session activation", ["too many onboarding steps", "unclear first action", "permission prompts", "time to value"]),
    ("mobile_app_activation", "App activation and core action completion.", "mobile app activation", "activation", ["first screen clarity", "core action visibility", "empty states", "habit loop clarity"]),
    ("paywall_conversion", "Paywall, trial, and subscription conversion.", "paywall or upgrade flow", "paywall conversion", ["paywall copy", "trial clarity", "pricing context", "upgrade CTA"]),
    ("booking_flow", "Bookings, appointments, and scheduling.", "booking flow friction", "booking completion", ["available slots visibility", "location selection", "calendar steps", "confirmation clarity"]),
    ("signup_completion", "Signup and account creation friction.", "signup flow friction", "signup completion", ["hidden social login", "required fields", "multi-step signup", "unclear submit CTA"]),
    ("demo_conversion", "B2B demo request conversion.", "demo request flow", "demo conversion", ["demo CTA visibility", "form length", "proof near CTA", "buyer-specific copy"]),
    ("case_study_proof", "Case studies and proof quality.", "case study proof gaps", "trust or conversion", ["missing direct quotes", "external links", "weak outcomes", "no screenshots"]),
    ("testimonial_trust", "Testimonials, review snippets, and trust.", "testimonial trust gaps", "trust", ["generic testimonials", "unnamed proof", "proof far from CTA", "missing customer details"]),
    ("landing_page_cta", "Landing-page CTA visibility and clarity.", "landing page CTA clarity", "conversion", ["above-fold CTA", "contrast", "competing CTAs", "CTA wording"]),
    ("ecommerce_checkout", "Ecommerce cart and checkout flow.", "checkout friction", "checkout completion", ["cart clarity", "shipping surprise", "payment steps", "discount field distraction"]),
    ("pricing_page_clarity", "Pricing-page clarity and plan comparison.", "pricing page clarity", "conversion", ["plan comparison", "feature overload", "hidden CTA", "unclear trial"]),
    ("saas_onboarding", "SaaS activation and setup.", "SaaS onboarding friction", "activation", ["setup checklist", "empty state", "integration step", "first value moment"]),
    ("b2b_enterprise_trust", "Enterprise trust and procurement readiness.", "enterprise trust gaps", "demo conversion or trust", ["security proof", "customer logos", "procurement proof", "case studies"]),
    ("healthcare_conversion", "Healthcare landing-page trust and conversion.", "healthcare trust and conversion friction", "booking or signup", ["clinical proof", "booking clarity", "privacy reassurance", "testimonial quality"]),
    ("wellness_app_retention", "Wellness app retention loops.", "wellness app retention cues", "retention", ["habit loop", "progress cues", "reminders", "first-session value"]),
    ("fintech_signup", "Fintech signup trust and compliance friction.", "fintech signup friction", "signup completion or trust", ["KYC expectation", "security proof", "pricing clarity", "trust badges"]),
    ("edtech_activation", "Education product activation.", "learning activation friction", "activation", ["first lesson clarity", "course preview", "progress path", "signup gate"]),
    ("marketplace_booking", "Marketplace search and booking.", "marketplace booking flow", "booking completion", ["search filters", "availability", "seller proof", "booking CTA"]),
    ("community_app_retention", "Community onboarding and retention.", "community app first-session friction", "retention", ["empty community risk", "first post prompt", "member proof", "notification loop"]),
    ("ai_tool_activation", "AI tool first value and prompt onboarding.", "AI tool activation friction", "activation", ["blank prompt state", "template visibility", "output examples", "first result"]),
    ("developer_tool_signup", "Developer-tool signup and docs activation.", "developer tool activation", "signup or activation", ["quickstart clarity", "API key flow", "docs CTA", "example code"]),
    ("productivity_app_onboarding", "Productivity app setup and first action.", "productivity app onboarding", "activation", ["workspace setup", "first task", "template overload", "calendar integration"]),
    ("recruitment_platform_conversion", "Recruitment platform lead capture.", "recruitment conversion friction", "lead capture", ["candidate/employer split", "job proof", "CTA clarity", "form friction"]),
    ("real_estate_lead_capture", "Real-estate inquiry and lead capture.", "real-estate lead capture", "inquiry conversion", ["property CTA", "availability", "contact form", "trust proof"]),
    ("travel_booking_flow", "Travel search and booking.", "travel booking friction", "booking completion", ["date selection", "pricing clarity", "availability", "checkout confidence"]),
    ("fitness_app_activation", "Fitness app workout activation.", "fitness app activation", "activation or retention", ["first workout", "plan selection", "progress cues", "subscription timing"]),
    ("meditation_app_retention", "Meditation app habit and retention.", "meditation app retention", "retention", ["first session", "streak cues", "course choice", "reminder setup"]),
    ("mental_health_app_trust", "Mental-health app trust and onboarding.", "mental-health trust and onboarding", "activation or trust", ["privacy reassurance", "care path clarity", "crisis disclaimer", "first session"]),
    ("creator_tool_activation", "Creator tool activation and first output.", "creator tool activation", "activation", ["template gallery", "blank canvas", "export CTA", "first project"]),
    ("agency_lead_gen", "Agency website lead generation.", "agency proof and CTA friction", "lead conversion", ["case study quality", "offer clarity", "CTA placement", "proof near form"]),
    ("local_service_booking", "Local service booking and quote flow.", "local service booking", "booking completion", ["service area", "availability", "quote form", "phone CTA"]),
    ("no_code_tool_activation", "No-code builder activation.", "no-code activation", "activation", ["template choice", "blank state", "publish CTA", "integration setup"]),
    ("cyber_security_proof", "Cybersecurity proof and trust.", "security proof gaps", "trust or demo conversion", ["security badges", "case studies", "compliance proof", "technical proof"]),
    ("analytics_dashboard_activation", "Analytics/dashboard activation.", "analytics activation", "activation", ["sample data", "integration setup", "empty dashboard", "first insight"]),
    ("crm_demo_conversion", "CRM demo and trial conversion.", "CRM demo/trial friction", "demo conversion", ["trial CTA", "buyer segmentation", "integration proof", "pipeline example"]),
    ("hrtech_signup", "HR software signup and trust.", "HRtech signup friction", "signup or demo conversion", ["employee proof", "compliance reassurance", "demo CTA", "buyer role clarity"]),
    ("insuretech_quote_flow", "Insurance quote flow.", "insurance quote friction", "quote completion", ["quote form steps", "coverage clarity", "trust proof", "price expectation"]),
    ("legaltech_lead_capture", "Legaltech lead capture and trust.", "legal service trust friction", "lead capture", ["practice area clarity", "consultation CTA", "proof", "form friction"]),
    ("climate_saas_proof", "Climate SaaS proof and ROI.", "climate SaaS proof gaps", "demo conversion", ["impact proof", "ROI claims", "case studies", "data credibility"]),
    ("ecommerce_subscription", "Subscription commerce conversion.", "subscription conversion", "subscription conversion", ["subscription terms", "first box value", "cancel clarity", "checkout CTA"]),
    ("gaming_app_retention", "Game onboarding and retention.", "game first-session friction", "retention", ["tutorial length", "first reward", "progression clarity", "store prompt"]),
    ("charity_donation_conversion", "Donation-page conversion.", "donation flow friction", "donation conversion", ["impact proof", "donation CTA", "amount choice", "trust badges"]),
    ("event_registration", "Event registration flow.", "event registration friction", "registration completion", ["ticket CTA", "agenda clarity", "speaker proof", "form steps"]),
    ("newsletter_signup", "Newsletter signup conversion.", "newsletter signup friction", "signup conversion", ["value promise", "sample issue", "form visibility", "proof"]),
    ("freemium_upgrade", "Freemium to paid upgrade.", "freemium upgrade friction", "upgrade conversion", ["usage limit clarity", "upgrade timing", "paywall copy", "feature comparison"]),
    ("app_store_listing", "App-store listing and public app signals.", "app-store listing friction", "activation or install conversion", ["review patterns", "screenshot clarity", "feature promise", "rating risk"]),
    ("visual_bug_hunter", "Visual formatting and layout bugs.", "visible formatting issues", "drop-off or conversion", ["mobile overflow", "overlapping content", "cropped CTA", "broken layout"]),
]


PRESET_PROFILES: dict[str, ToneProfile] = {
    name: _profile(name, description, surface, outcome, priorities)
    for name, description, surface, outcome, priorities in PRESET_SPECS
}


def preset_names() -> list[str]:
    return sorted(PRESET_PROFILES)


def get_preset_profile(name: str) -> ToneProfile | None:
    return PRESET_PROFILES.get((name or "").strip())


def preset_options() -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "description": profile.description,
            "opening_style": profile.opening_style,
        }
        for name, profile in sorted(PRESET_PROFILES.items())
    ]
