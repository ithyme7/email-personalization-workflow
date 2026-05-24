from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from input_loader import load_leads
from batch_runner import _base_row
from email_verification import email_from_original_columns


def test_client_sheet_alias_columns_with_trailing_spaces() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "client_sheet.csv"
        pd.DataFrame(
            [
                {
                    "App Store": "https://play.google.com/store/apps/details?id=test",
                    "Company Name ": "Little Otter\r",
                    "Website ": "littleotterhealth.com",
                    "Linkedin": "https://linkedin.com/company/little-otter",
                    "First Name ": "Helen Egger\r",
                    "Job Tile ": "Co-Founder",
                    "Email": "helen@example.com",
                }
            ]
        ).to_csv(path, index=False)
        leads = load_leads(path, "campaign", deduplicate=False)
    assert len(leads) == 1
    assert leads[0].is_valid
    assert leads[0].company_name == "Little Otter"
    assert leads[0].website_url == "https://littleotterhealth.com"
    assert leads[0].recipient_name == "Helen Egger"
    assert leads[0].recipient_role == "Co-Founder"
    assert leads[0].app_store_url.startswith("https://play.google.com")
    assert leads[0].original_columns["Company Name"] == "Little Otter"
    assert _base_row(leads[0])["input__Email"] == "helen@example.com"


def test_clay_style_duplicate_organization_name_sheet_loads_contacts() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "mental_health_sheet.csv"
        path.write_text(
            "\n".join(
                [
                    "Organization Name,Last Funding Amount,Approx USD Equivalent,Website,Twitter,Facebook,LinkedIn,Contact Email,Number of Articles,Number of Employees,Number of Founders,Founders,icp_match,b2c_category,Organization Name,Person Name,Role,Email,Status,Linkedin,Source,Personalised Line",
                    "Behavidence,\"$4,300,000\",\"$4,300,000\",www.behavidence.com,—,https://www.facebook.com/behavidence,https://www.linkedin.com/company/behavidence,health@behavidence.com,42,1-10,4,\"Girish Srinivasan, Roy Cohen\",yes,Mental Health,behavidence,Girish Srinivasan,Co-Founder,girish@behavidence.com,Verified,http://www.linkedin.com/in/srinivasangirish,Linkedin,",
                    ",,,,,,,,,,,,,,,Roy Cohen,Co-Founder,roy@behavidence.com,Verified,http://www.linkedin.com/in/roy-cohen-281805200,Linkedin,",
                ]
            ),
            encoding="utf-8",
        )
        leads = load_leads(path, "campaign", deduplicate=False)

    assert len(leads) == 2
    assert all(lead.is_valid for lead in leads)
    assert leads[0].company_name == "Behavidence"
    assert leads[0].website_url == "https://behavidence.com"
    assert leads[0].recipient_name == "Girish Srinivasan"
    assert leads[0].linkedin_url == "http://www.linkedin.com/in/srinivasangirish"
    assert leads[1].company_name == "Behavidence"
    assert leads[1].website_url == "https://behavidence.com"
    assert leads[1].recipient_name == "Roy Cohen"
    assert leads[1].linkedin_url == "http://www.linkedin.com/in/roy-cohen-281805200"
    assert leads[1].original_columns["Organization Name"] == ""


def test_generated_contact_export_schema_loads_into_personalizer() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "personalizer_contacts.csv"
        pd.DataFrame(
            [
                {
                    "First Name": "Katie",
                    "Copy": "",
                    "Personalization Line": "",
                    "Company Name": "after app",
                    "LinkedIn Profile": "https://www.linkedin.com/in/katiedissanayake",
                    "Personal Email": "katie@afterapp.com",
                    "Company Website": "https://www.afterapp.com/",
                }
            ]
        ).to_csv(path, index=False)

        leads = load_leads(path, "campaign", deduplicate=False)

    assert len(leads) == 1
    assert leads[0].company_name == "after app"
    assert leads[0].website_url == "https://afterapp.com"
    assert leads[0].recipient_name == "Katie"
    assert leads[0].linkedin_url == "https://www.linkedin.com/in/katiedissanayake"
    assert email_from_original_columns(leads[0].original_columns) == "katie@afterapp.com"


if __name__ == "__main__":
    test_client_sheet_alias_columns_with_trailing_spaces()
    test_clay_style_duplicate_organization_name_sheet_loads_contacts()
    test_generated_contact_export_schema_loads_into_personalizer()
    print("input_loader_alias_tests_ok")
