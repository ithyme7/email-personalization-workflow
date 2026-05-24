from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lead_generator import (
    app_store_brand_name,
    app_store_payload_to_leads,
    build_app_store_terms,
    build_lead_search_queries,
    generate_leads,
    generated_leads_dataframe,
    parse_search_results,
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
