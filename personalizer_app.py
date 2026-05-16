from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from cli import run
from config import load_settings
from tone_profiles import available_tone_profiles


DEFAULT_CONTEXT = "We help mobile app teams with this type of work, figure out where users drop off and why."


def _ask_path(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip().strip('"')
    return value or default


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "j", "ja"}


def _pick_csv_file() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return ""

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Choose lead CSV",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )
    root.destroy()
    return path or ""


def _resolve_input_path(default_input: str = "") -> str:
    print("Stap 1 - kies je input CSV")
    print("Druk op Enter om een bestand te kiezen, of plak direct een pad.")
    while True:
        typed = _ask_path("CSV input path", default_input)
        input_path = typed
        if not input_path:
            input_path = _pick_csv_file()
        if input_path and Path(input_path).exists():
            return input_path
        print("Ik kan dat CSV-bestand niet vinden. Probeer opnieuw.")
        default_input = ""


def _default_output_path(input_path: str) -> str:
    source = Path(input_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return str(source.with_name(f"{source.stem}_personalization_review_{stamp}.xlsx"))


def _resolve_output_path(input_path: str) -> str:
    print("")
    print("Stap 2 - kies waar de Excel-output moet komen")
    default_output = _default_output_path(input_path)
    output_path = _ask_path("Output Excel/CSV path", default_output)
    output = Path(output_path)
    if output.suffix.lower() not in {".xlsx", ".csv"}:
        output = output.with_suffix(".xlsx")
    return str(output)


def _maybe_prompt_for_api_key(settings):
    if settings.has_active_llm_key:
        return settings
    if settings.llm_provider != "gemini":
        return settings

    print("Wil je nu je Gemini API key plakken?")
    print("Hij wordt alleen voor deze run gebruikt en niet opgeslagen in de code.")
    print("Let op: plak deze key alleen in je eigen lokale venster, niet in screenshots of chats.")
    key = input("Gemini API key, leeg laten = research-only: ").strip()
    if not key:
        return settings
    os.environ["GEMINI_API_KEY"] = key
    print("Gemini key geladen voor deze run.")
    return load_settings()


def _make_args(input_path: str, output_path: str, campaign_context: str, tone_profile: str) -> argparse.Namespace:
    return argparse.Namespace(
        input=input_path,
        output=output_path,
        campaign_context=campaign_context,
        manual_review_mode=True,
        reuse_duplicate_personalization=True,
        client_batch_output=True,
        deep_research=True,
        tone_profile=tone_profile,
        log_level="INFO",
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stdout)
    print("")
    print("Email Personalization Workflow")
    print("==============================")
    print("This tool creates a reviewable personalization output from a CSV.")
    print("")

    settings = load_settings()
    if settings.llm_provider == "gemini":
        key_name = "GEMINI_API_KEY"
    elif settings.llm_provider == "openrouter":
        key_name = "OPENROUTER_API_KEY"
    elif settings.llm_provider == "deepseek":
        key_name = "DEEPSEEK_API_KEY"
    else:
        key_name = "OPENAI_API_KEY"
    print(f"Model provider: {settings.llm_provider}")
    print(f"Model: {settings.model_name}")
    print("")
    if not settings.has_active_llm_key:
        print(f"NOTE: {key_name} is not set.")
        print("The tool will still collect public research and create a readable review workbook.")
        print("New AI-written personalization lines need an active API key/quota.")
        print("")
        settings = _maybe_prompt_for_api_key(settings)
        if settings.has_active_llm_key:
            print("")
            print("API key detected. Full AI evidence/writing/QC flow will run.")
            print("")

    default_input = str(Path("data/input/sample_companies.csv").resolve())
    if not Path(default_input).exists():
        default_input = ""

    input_path = _resolve_input_path(default_input)
    output_path = _resolve_output_path(input_path)
    print("")
    print("Stap 3 - campaign context")
    campaign_context = _ask_path("Campaign context", DEFAULT_CONTEXT)
    print("")
    print("Stap 4 - tone profile")
    profiles = ", ".join(available_tone_profiles()) or "friction_first"
    print(f"Beschikbaar: {profiles}")
    tone_profile = _ask_path("Tone profile", settings.tone_profile)
    open_after = _ask_yes_no("Open de Excel automatisch als hij klaar is?", True)

    print("")
    print("Running workflow...")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print("")

    try:
        rows = run(_make_args(input_path, output_path, campaign_context, tone_profile))
    except Exception as exc:
        print("")
        print(f"Workflow failed: {exc}")
        input("Press Enter to close...")
        raise

    needs_review = sum(1 for row in rows if str(row.get("needs_manual_review", "")).lower() in {"true", "yes", "waar", "1"})
    generated = sum(1 for row in rows if str(row.get("opening_line", "")).strip())
    print("")
    print("Done.")
    print(f"Output saved to: {Path(output_path).resolve()}")
    print(f"Rows exported: {len(rows)}")
    print(f"Tone profile: {tone_profile}")
    print(f"Rows with generated personalization line: {generated}")
    print(f"Rows marked for manual review: {needs_review}")
    if not settings.has_active_llm_key:
        print("Note: no active API key was found, so this run is mainly research/review output.")
    elif generated == 0:
        print("Note: the API key was present, but AI generation did not produce lines. Check reviewer notes in the workbook for the exact API/preflight error.")
    print("")
    if open_after:
        try:
            os.startfile(str(Path(output_path).resolve()))
        except OSError as exc:
            print(f"Could not open file automatically: {exc}")
    try:
        input("Press Enter to close...")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
