from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from input_loader import load_leads
from batch_runner import _base_row


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


if __name__ == "__main__":
    test_client_sheet_alias_columns_with_trailing_spaces()
    print("input_loader_alias_tests_ok")
