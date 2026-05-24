from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lead_generator import (
    DiscoveryCache,
    GeneratedLead,
    app_store_brand_name,
    app_store_payload_to_leads,
    build_app_store_terms,
    build_lead_search_queries,
    contact_export_dataframe,
    discover_company_linkedin,
    generate_leads,
    generated_leads_dataframe,
    parse_contact_candidates,
    parse_search_results,
    search_contact_candidates,
)


DUCK_HTML = """
<div class="result">
  <a class="result__a" href="/l/?uddg=https%3A%2F%2Fwww.littleotterhealth.com%2Fpricing">Little Otter - Mental health app for families</a>
  <a class="result__snippet">A mental health app and care platform for families.</a>
</div>
<div class="result">
  <a class="result__a" href="https://apps.apple.com/us/app/little-otter/id123">Little Otter on the App Store</a>
  <a class="result__snippet">App Store listing.</a>
</div>
<div class="result">
  <a class="result__a" href="https://www.getinflow.io/">Inflow ADHD - App and coaching platform</a>
  <a class="result__snippet">ADHD app with onboarding and pricing.</a>
</div>
"""


class FakeResponse:
    text = DUCK_HTML

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def get(self, *args, **kwargs) -> FakeResponse:
        return FakeResponse()


class FakeSearchResponse:
    status_code = 200
    text = """
Title: example founder linkedin at DuckDuckGo

## [Jane Doe - LinkedIn](https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.linkedin.com%2Fin%2Fjane-doe-123&rut=abc)
Jane Doe is Founder and CEO at Example.
"""


class FakeSearchSession:
    def get(self, *args, **kwargs) -> FakeSearchResponse:
        return FakeSearchResponse()


class FakeCompanySearchResponse:
    status_code = 200
    text = """
Title: Example App LinkedIn at DuckDuckGo

## [Example App - LinkedIn](https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.linkedin.com%2Fcompany%2Fexample-app%3Ftrk%3Dpublic_profile&rut=abc)
Example App company page on LinkedIn.
"""


class FakeCompanySearchSession:
    def get(self, *args, **kwargs) -> FakeCompanySearchResponse:
        return FakeCompanySearchResponse()


class CountingSearchSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, *args, **kwargs) -> FakeSearchResponse:
        self.calls += 1
        return FakeSearchResponse()


def test_parse_search_results_decodes_duckduckgo_links() -> None:
    results = parse_search_results(DUCK_HTML)
    assert results[0]["url"] == "https://www.littleotterhealth.com/pricing"
    assert "mental health app" in results[0]["title"].lower()


def test_generate_leads_dedupes_and_filters_directory_domains() -> None:
    leads = generate_leads(["mental health app"], max_leads=10, session=FakeSession())  # type: ignore[arg-type]
    assert [lead.website for lead in leads] == [
        "https://littleotterhealth.com",
        "https://getinflow.io",
    ]
    df = generated_leads_dataframe(leads)
    assert df.columns[:6].tolist() == ["Organization Name", "Website", "App Store URL", "Person Name", "Role", "Email"]
    assert df.loc[0, "Source"] == "public_web_search"


def test_build_lead_search_queries_uses_extra_angles() -> None:
    queries = build_lead_search_queries("mental health", "mobile apps", "US", "pricing\nfounder")
    assert queries == [
        "mental health mobile apps US pricing -jobs -blog",
        "mental health mobile apps US founder -jobs -blog",
    ]


def test_app_store_payload_to_leads_creates_personalizer_ready_rows() -> None:
    payload = {
        "results": [
            {
                "trackName": "Rootd",
                "sellerName": "Simply Rooted Media Inc.",
                "trackViewUrl": "https://apps.apple.com/us/app/rootd/id1289018369",
                "sellerUrl": "https://www.rootd.io",
                "primaryGenreName": "Health & Fitness",
                "description": "An anxiety and panic attack relief app with breathing tools.",
            }
        ]
    }
    leads = app_store_payload_to_leads(payload, "mental health anxiety")
    assert len(leads) == 1
    assert leads[0].organization_name == "Rootd"
    assert leads[0].website == "https://rootd.io"
    assert leads[0].app_store_url.startswith("https://apps.apple.com")
    df = generated_leads_dataframe(leads)
    assert df.loc[0, "App Store URL"].startswith("https://apps.apple.com")
    assert df.loc[0, "Source"] == "apple_app_store_search"


def test_build_app_store_terms_combines_niche_and_terms() -> None:
    assert build_app_store_terms("mental health", "sleep\nadhd") == [
        "mental health sleep",
        "mental health adhd",
    ]


def test_app_store_brand_name_prefers_product_brand_over_legal_seller() -> None:
    assert app_store_brand_name("BetterHelp - Therapy", "Compile, Inc.") == "BetterHelp"
    assert app_store_brand_name("Talkspace: Virtual Therapy App", "Groop Internet Platform inc.") == "Talkspace"


def test_parse_contact_candidates_prefers_person_level_contacts() -> None:
    html = """
    <html>
      <body>
        <p>Jane Doe Co-Founder & CEO</p>
        <a href="mailto:jane@example.app">jane@example.app</a>
        <a href="mailto:hello@example.app">hello@example.app</a>
        <a href="https://www.linkedin.com/in/jane-doe-123">LinkedIn</a>
      </body>
    </html>
    """
    candidates = parse_contact_candidates(html, "https://example.app/team", company_domain="example.app")
    assert candidates[0].first_name == "Jane"
    assert candidates[0].email == "jane@example.app"
    assert candidates[0].linkedin_url == "https://www.linkedin.com/in/jane-doe-123"
    assert "hello@example.app" not in {candidate.email for candidate in candidates}


def test_contact_export_dataframe_matches_personalizer_contact_schema() -> None:
    lead = app_store_payload_to_leads(
        {
            "results": [
                {
                    "trackName": "Rootd",
                    "sellerName": "Simply Rooted Media Inc.",
                    "trackViewUrl": "https://apps.apple.com/us/app/rootd/id1289018369",
                    "sellerUrl": "https://www.rootd.io",
                    "primaryGenreName": "Health & Fitness",
                    "description": "An anxiety app.",
                }
            ]
        },
        "mental health anxiety",
    )[0]
    candidates = parse_contact_candidates(
        "<p>Ania Wysocka Founder</p><a href='mailto:ania@rootd.io'>ania@rootd.io</a>",
        "https://rootd.io/about",
        company_domain="rootd.io",
    )
    df = contact_export_dataframe([lead], {lead.app_store_url: candidates})
    assert df.columns.tolist() == [
        "First Name",
        "Copy",
        "Personalization Line",
        "Company Name",
        "LinkedIn Profile",
        "Personal Email",
        "Company Website",
    ]
    assert df.loc[0, "First Name"] == "Ania"
    assert df.loc[0, "Company Name"] == "Rootd"
    assert df.loc[0, "Personal Email"] == "ania@rootd.io"


def test_search_contact_candidates_extracts_linkedin_profiles_from_public_results() -> None:
    lead = GeneratedLead(
        organization_name="Example",
        website="https://example.app",
        app_store_url="",
        source="test",
        discovery_query="example",
        source_title="",
        source_snippet="",
        lead_score=80,
        lead_notes="",
    )
    candidates = search_contact_candidates(lead, session=FakeSearchSession())  # type: ignore[arg-type]
    assert candidates[0].first_name == "Jane"
    assert candidates[0].linkedin_url == "https://www.linkedin.com/in/jane-doe-123"


def test_discover_company_linkedin_prefers_owned_site_links() -> None:
    lead = GeneratedLead(
        organization_name="Example App",
        website="https://example.app",
        app_store_url="",
        source="test",
        discovery_query="example",
        source_title="",
        source_snippet="",
        lead_score=80,
        lead_notes="",
    )
    pages = [
        (
            "https://example.app",
            '<a href="https://www.linkedin.com/company/example-app?trk=footer">LinkedIn</a>',
        )
    ]
    result = discover_company_linkedin(lead, pages=pages, use_search_fallback=False)
    assert result is not None
    assert result.url == "https://www.linkedin.com/company/example-app"
    assert result.confidence >= 80


def test_discover_company_linkedin_uses_public_search_fallback() -> None:
    lead = GeneratedLead(
        organization_name="Example App",
        website="https://example.app",
        app_store_url="",
        source="test",
        discovery_query="example",
        source_title="",
        source_snippet="",
        lead_score=80,
        lead_notes="",
    )
    result = discover_company_linkedin(
        lead,
        pages=[],
        session=FakeCompanySearchSession(),  # type: ignore[arg-type]
        cache=DiscoveryCache(enabled=False),
    )
    assert result is not None
    assert result.url == "https://www.linkedin.com/company/example-app"
    assert "public_search" in result.notes


def test_search_contact_candidates_uses_discovery_cache() -> None:
    lead = GeneratedLead(
        organization_name="Cache Example",
        website="https://cache-example.app",
        app_store_url="",
        source="test",
        discovery_query="example",
        source_title="",
        source_snippet="",
        lead_score=80,
        lead_notes="",
    )
    session = CountingSearchSession()
    cache = DiscoveryCache(enabled=True, namespace=f"unit-test-contact-search-{id(session)}")

    first = search_contact_candidates(
        lead,
        session=session,  # type: ignore[arg-type]
        cache=cache,
        max_search_queries=1,
    )
    second = search_contact_candidates(
        lead,
        session=session,  # type: ignore[arg-type]
        cache=cache,
        max_search_queries=1,
    )

    assert session.calls == 1
    assert first[0].linkedin_url == second[0].linkedin_url
