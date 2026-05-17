from __future__ import annotations

import argparse
import logging

from batch_runner import ProgressCallback, run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate researched, reviewable email personalization notes from a CSV.")
    parser.add_argument("--input", required=True, help="Path to input CSV")
    parser.add_argument("--output", required=True, help="Path to output CSV or XLSX")
    parser.add_argument("--campaign-context", default="", help="Default campaign context when a row does not provide one")
    parser.add_argument(
        "--manual-review-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Export weak or failed rows for review instead of failing the whole batch",
    )
    parser.add_argument(
        "--reuse-duplicate-personalization",
        action="store_true",
        help="Process each company once, then reuse the same personalization for duplicate contact rows",
    )
    parser.add_argument(
        "--client-batch-output",
        action="store_true",
        help="Export compact client columns: company, person, role, website, evidence found, personalized line, flags, review",
    )
    parser.add_argument(
        "--deep-research",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add public app-store discovery plus supplied LinkedIn/app-flow/news/screenshot context to the research prompt",
    )
    parser.add_argument(
        "--tone-profile",
        default="",
        help="Tone profile name or JSON path. Built-ins: friction_first, proof_led_b2b, founder_casual",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


if __name__ == "__main__":
    parsed_args = parse_args()
    logging.basicConfig(level=parsed_args.log_level, format="%(levelname)s: %(message)s")
    run(parsed_args)
