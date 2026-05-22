"""Email Personalization Workflow — CLI App

Deze app biedt een interactief hoofdmenu voor:
- Personalisatie-runs starten (met A/B testing en send-time optimalisatie)
- Feedback invoeren (open/reply/conversion)
- Dashboards voor feedback, A/B testen, send-time advies, en sequences
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from config import load_settings, Settings
from feedback import (
    SendFeedback,
    get_feedback_summary,
    get_failing_patterns,
    get_success_patterns,
    ingest_feedback_results,
    init_feedback_db,
    load_feedback,
)
from personalizer import run  # type: ignore
from schemas import stable_hash
from send_time_optimizer import compute_send_time, format_send_time, compare_send_times
from tone_profiles import available_tone_profiles, load_tone_profile

# --- Configuratie ---
DEFAULT_CONTEXT = ""


# --- Hulpfuncties ---
def _ask_path(prompt: str, default: str = "") -> str:
    """Vraag om een bestandspad of map, met een standaardwaarde."""
    result = input(f"  {prompt} [{default}]: ").strip()
    return result or default


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Vraag om een ja/nee antwoord."""
    default_str = "j" if default else "n"
    result = input(f"  {prompt} [{default_str}]: ").strip().lower()
    if not result:
        return default
    return result in {"j", "yes", "y", "ja"}


def _resolve_input_path(default_input: str) -> str:
    """Los het invoerbestand op."""
    return _ask_path("Invoer CSV-bestand", default_input)


def _resolve_output_path(input_path: str) -> str:
    """Bepaal het standaard uitvoerpad."""
    input_file = Path(input_path)
    return str(input_file.parent / f"{input_file.stem}_output.xlsx")


# ---- Hoofdprogramma ----
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

    # ---- Hoofdmenu ----
    while True:
        print("")
        print("=== HOOFDMENU ===")
        print("  [1] Nieuwe personalisatie-run starten")
        print("  [2] Feedback invoeren (open/reply/conversion resultaten)")
        print("  [3] Feedback dashboard bekijken")
        print("  [4] Send-time advies bekijken")
        print("  [5] A/B Test dashboard")
        print("  [6] Sequence-overzicht bekijken")
        print("  [q] Afsluiten")
        print("")
        choice = input("Optie: ").strip().lower()

        if choice == "q":
            print("Tot ziens!")
            break
        elif choice == "1":
            _run_personalization(settings)
        elif choice == "2":
            _feed_back_results()
        elif choice == "3":
            _show_feedback_dashboard()
        elif choice == "4":
            _show_send_time_advice(settings)
        elif choice == "5":
            _show_ab_dashboard()
        elif choice == "6":
            _show_sequence_overview()
        else:
            print("Ongeldige optie. Probeer opnieuw.")


def _run_personalization(settings: Settings) -> None:
    """Voer een volledige personalisatie-run uit."""
    from feedback import init_feedback_db

    init_feedback_db()

    default_input = str(Path("data/input/sample_companies.csv").resolve())
    if not Path(default_input).exists():
        default_input = ""

    input_path = _resolve_input_path(default_input)
    output_path = _resolve_output_path(input_path)

    # Option: send-time optimization toggle
    if settings.send_time_optimization_enabled:
        print("  Send-time optimalisatie is AAN.")
    else:
        opt = input("  Send-time optimalisatie inschakelen? [j/n] [n]: ").strip().lower()
        if opt in {"j", "yes", "y", "ja"}:
            os.environ["SEND_TIME_OPTIMIZATION_ENABLED"] = "true"
            settings = load_settings()  # reload

    # Option: A/B testing toggle
    if settings.ab_testing_enabled:
        print("  A/B testing is AAN.")
    else:
        opt = input("  A/B testing inschakelen? [j/n] [n]: ").strip().lower()
        if opt in {"j", "yes", "y", "ja"}:
            os.environ["AB_TESTING_ENABLED"] = "true"
            settings = load_settings()

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

    # Show send-time summary
    if settings.send_time_optimization_enabled:
        timed = sum(1 for row in rows if row.get("suggested_send_time_utc"))
        print(f"  Send-time advies berekend voor {timed}/{len(rows)} leads")

    # Show A/B summary
    if settings.ab_testing_enabled:
        ab_leads = sum(1 for row in rows if row.get("ab_variant_id"))
        print(f"  A/B test varianten toegewezen aan {ab_leads}/{len(rows)} leads")

    # Show sequence summary
    if settings.follow_up_sequence_enabled:
        seq_leads = sum(1 for row in rows if row.get("sequence_step"))
        print(f"  Follow-up sequences gegenereerd voor {seq_leads} leads")

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
        print("Note: the API key was present, but AI generation did not produce lines.")
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


def _feed_back_results() -> None:
    """Interactieve feedback-invoer: voer open/reply/conversion resultaten in."""
    print("")
    print("=== Feedback Invoer ===")
    print("Voer de daadwerkelijke resultaten in voor verstuurde emails.")
    print("")

    run_id = input("Run-ID (leeg = laatste run): ").strip()

    # Bepaal run_id als niet opgegeven
    if not run_id:
        feedback_rows = load_feedback()
        if feedback_rows:
            run_id = feedback_rows[0].run_id
            print(f"Gebruik run: {run_id}")
        else:
            print("Geen feedback records gevonden. Voer eerst een run uit.")
            input("Press Enter to close...")
            return

    # Toon beschikbare records
    all_feedback = load_feedback(run_id)
    pending = [fb for fb in all_feedback if not fb.was_opened and not fb.got_reply and not fb.converted]

    if not pending:
        print("Alle records voor deze run hebben al feedback.")
        summary = get_feedback_summary()
        print("")
        print("=== Huidige Samenvatting ===")
        _print_summary(summary)
        input("Press Enter to close...")
        return

    print(f"Er zijn {len(pending)} records zonder feedback.")
    print("")

    # Bulk-invoer via CSV of per-record
    mode = input("Bulk invoeren via bestand [b] of per record handmatig [h]? [b/h]: ").strip().lower()

    if mode == "b":
        _feed_back_bulk(run_id, all_feedback)
    else:
        _feed_back_interactive(run_id, all_feedback)


def _feed_back_interactive(run_id: str, all_feedback: list[Any]) -> None:
    """Per-record feedback-invoer."""
    result_rows: list[dict[str, Any]] = []
    for fb in all_feedback:
        print("")
        print(f"--- {fb.company_name} ({fb.recipient_name}, {fb.recipient_role}) ---")
        print(f"  Opening line: {fb.opening_line[:80]}...")
        print(f"  Angle: {fb.chosen_angle}")
        if fb.sent_at:
            print(f"  Verstuurd: {fb.sent_at}")
        if hasattr(fb, "suggested_send_time_utc") and fb.suggested_send_time_utc:
            print(f"  Advies send-time: {fb.suggested_send_time_utc} ({fb.suggested_send_timezone})")

        opened = input("  Geopend? [j/n/enter=sla over]: ").strip().lower()
        if opened == "":
            continue

        result: dict[str, Any] = {"example_id": fb.example_id}
        result["was_opened"] = opened in {"j", "yes", "y", "ja"}

        if result["was_opened"]:
            replied = input("  Reply ontvangen? [j/n/enter=nee]: ").strip().lower()
            result["got_reply"] = replied in {"j", "yes", "y", "ja"}

            if result["got_reply"]:
                reply_text = input("  Reply tekst (optioneel, enter=overslaan): ").strip()
                if reply_text:
                    result["reply_text"] = reply_text

                try:
                    minutes = int(input("  Tijd tot reply in minuten (enter=onbekend): ").strip() or "0")
                    result["time_to_reply_minutes"] = minutes
                except ValueError:
                    pass

                converted = input("  Conversie? [j/n/enter=nee]: ").strip().lower()
                result["converted"] = converted in {"j", "yes", "y", "ja"}

                if result["converted"]:
                    conv_type = input("  Conversie type (meeting/demo/trial/sale/partnership/enter): ").strip()
                    result["conversion_type"] = conv_type
                    notes = input("  Conversie opmerkingen (optioneel): ").strip()
                    if notes:
                        result["conversion_notes"] = notes

        result_rows.append(result)

    if result_rows:
        updated = ingest_feedback_results(run_id, result_rows)
        print(f"\n{updated} feedback records bijgewerkt.")
        _show_summary_after_feedback(run_id)


def _feed_back_bulk(run_id: str, all_feedback: list[Any]) -> None:
    """Bulk feedback invoer via een eenvoudig interactief proces."""
    fb_map = {fb.example_id: fb for fb in all_feedback}

    print("")
    print("CSV-formaat verwacht (kopieer/plak of typ per regel):")
    print("  example_id,was_opened,got_reply,converted,conversion_type")
    print("  was_opened: 0/1, got_reply: 0/1, converted: 0/1")
    print("  conversion_type: meeting|demo|trial|sale|partnership (optioneel)")
    print("")
    print("Voer de feedback-resultaten in (lege regel = klaar):")
    print("")

    results: list[dict[str, Any]] = []
    while True:
        line = input("> ").strip()
        if not line:
            break
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            print("  Fout: minimaal 3 kolommen nodig (example_id, was_opened, got_reply)")
            continue

        example_id = parts[0]
        if example_id not in fb_map:
            print(f"  Waarschuwing: example_id '{example_id}' niet gevonden, genegeerd.")
            continue

        try:
            result: dict[str, Any] = {"example_id": example_id}
            result["was_opened"] = int(parts[1]) == 1
            result["got_reply"] = int(parts[2]) == 1

            if len(parts) >= 4:
                result["converted"] = int(parts[3]) == 1
            else:
                result["converted"] = False

            if len(parts) >= 5 and result["converted"]:
                result["conversion_type"] = parts[4]

            results.append(result)
        except ValueError:
            print("  Fout: was_opened, got_reply, converted moeten 0 of 1 zijn.")

    if results:
        updated = ingest_feedback_results(run_id, results)
        print(f"\n{updated} feedback records bijgewerkt.")
        _show_summary_after_feedback(run_id)


def _show_summary_after_feedback(run_id: str) -> None:
    """Toon een korte samenvatting na feedback-invoer."""
    summary = get_feedback_summary()
    print("")
    print("=== Bijgewerkte Samenvatting ===")
    _print_summary(summary)


def _print_summary(summary: dict[str, Any]) -> None:
    """Print een feedback samenvatting."""
    print(f"  Totale sends:    {summary['total_sends']}")
    print(f"  Open rate:       {summary['open_rate']}%")
    print(f"  Reply rate:      {summary['reply_rate']}%")
    print(f"  Conversie rate:  {summary['conversion_rate']}%")
    print(f"  Avg reply tijd:  {summary['avg_reply_time_minutes']} min")

    if summary["by_friction_type"]:
        print("")
        print("  Per friction type:")
        for entry in summary["by_friction_type"][:5]:
            ft = entry.get("friction_type", "onbekend")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            bar = "█" * int(cr / 5) + "░" * (20 - int(cr / 5))
            print(f"    - {ft}: {bar} {cr:5.1f}% ({n} sends)")

    if summary["by_angle_category"]:
        print("")
        print("  Per angle category:")
        for entry in summary["by_angle_category"]:
            ac = entry.get("angle_category", "onbekend")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            bar = "█" * int(cr / 5) + "░" * (20 - int(cr / 5))
            print(f"    - {ac}: {bar} {cr:5.1f}% ({n} sends)")
    input("Press Enter to close...")


def _show_feedback_dashboard() -> None:
    """Toon het uitgebreide feedback dashboard."""
    summary = get_feedback_summary()
    success = get_success_patterns(limit=5)
    failing = get_failing_patterns(limit=5)

    print("")
    print("=== 📊 Feedback Dashboard ===")
    print("")
    print(f"  Totale sends:       {summary['total_sends']}")
    print(f"  Open rate:          {summary['open_rate']}%")
    print(f"  Reply rate:         {summary['reply_rate']}%")
    print(f"  Conversie rate:     {summary['conversion_rate']}%")
    print(f"  Avg reply tijd:     {summary['avg_reply_time_minutes']} min")

    if summary["total_sends"] == 0:
        print("\n  Nog geen feedback data beschikbaar.")
        input("Press Enter to close...")
        return

    if summary["by_friction_type"]:
        print("\n  ── Per Friction Type ──")
        for entry in summary["by_friction_type"]:
            ft = entry.get("friction_type", "onbekend")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            bar = "█" * min(int(cr / 5), 20) + "░" * (20 - min(int(cr / 5), 20))
            print(f"    {ft:35s} {bar} {cr:5.1f}% ({n} sends)")

    if summary["by_angle_category"]:
        print("\n  ── Per Angle Category ──")
        for entry in summary["by_angle_category"]:
            ac = entry.get("angle_category", "onbekend")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            bar = "█" * min(int(cr / 5), 20) + "░" * (20 - min(int(cr / 5), 20))
            print(f"    {ac:35s} {bar} {cr:5.1f}% ({n} sends)")

    if success:
        print("\n  ✅ Wat Werkt (top 5)")
        for p in success:
            angle = p.get("chosen_angle", "unknown")
            conv = p.get("conv_rate", 0)
            n = p.get("times_used", 0)
            email_type = p.get("product_surface_type", "?")
            print(f"    • {angle} → {conv}% conv ({n}x) [{email_type}]")

    if failing:
        print("\n  ❌ Wat Niet Werkt")
        for p in failing:
            angle = p.get("chosen_angle", "unknown")
            n = p.get("times_used", 0)
            cr = p.get("conv_rate", 0)
            print(f"    • {angle} ({n}x, {cr}% conv)")

    input("\nPress Enter to close...")


def _show_send_time_advice(settings: Settings) -> None:
    """Toon send-time advies voor leads."""
    print("")
    print("=== ⏰ Send-time Optimalisatie ===")
    print("")

    if not settings.send_time_optimization_enabled:
        print("  Send-time optimalisatie is UITGESCHAKELD.")
        print("  Zet FOLLOW_TIME_OPTIMIZATION_ENABLED=true om te activeren.")
        input("Press Enter to close...")
        return

    # Laad leads uit de laatste run
    from batch_runner import _resolve_output_path
    import glob

    output_dir = Path("data/output")
    recent_files = sorted(glob.glob(str(output_dir / "*_output.*")))
    if not recent_files:
        print("  Geen outputbestanden gevonden.")
        input("Press Enter to close...")
        return

    latest = recent_files[-1]
    print(f"  Laatste output: {latest}")
    print("")

    try:
        import pandas as pd
        df = pd.read_excel(latest) if latest.endswith(".xlsx") else pd.read_csv(latest)

        if "suggested_send_time_utc" not in df.columns:
            print("  Geen send-time data in dit bestand (run opnieuw met send-time enabled).")
            input("Press Enter to close...")
            return

        timed_rows = df[df["suggested_send_time_utc"].notna() & (df["suggested_send_time_utc"] != "")]
        if timed_rows.empty:
            print("  Geen send-time advies beschikbaar.")
            input("Press Enter to close...")
            return

        print(f"  Send-time advies voor {len(timed_rows)} leads:\n")
        print(f"  {'Company':<30s} {'Tijd (UTC)':<24s} {'Tz':<18s} {'Conf':>6s}  Bron")
        print(f"  {'-'*30} {'-'*23} {'-'*17} {'-'*5}  {'-'*20}")

        for _, row in timed_rows.head(30).iterrows():
            company = str(row.get("company_name", ""))[:28]
            time_str = str(row.get("suggested_send_time_utc", ""))[:22]
            tz = str(row.get("suggested_send_timezone", ""))[:16]
            conf = row.get("send_time_confidence", 0)
            source = str(row.get("send_time_source", ""))
            conf_str = f"{conf:.0%}" if conf > 0 else "n.v.t."
            print(f"  {company:<30s} {time_str:<24s} {tz:<18s} {conf_str:>6s}  {source}")

        avg_conf = timed_rows["send_time_confidence"].mean() if timed_rows["send_time_confidence"].dtype in ["float64", "int64", "int32"] else 0
        print(f"\n  Gemiddelde confidence: {avg_conf:.0%}")

    except ImportError:
        print("  Pandas niet beschikbaar. Installeer met: pip install pandas openpyxl")
    except Exception as e:
        print(f"  Fout bij laden bestand: {e}")

    input("\nPress Enter to close...")


def _show_ab_dashboard() -> None:
    """Toon A/B test dashboard met experiment resultaten."""
    print("")
    print("=== 🧪 A/B Test Dashboard ===")
    print("")

    from ab_testing import load_experiments, ExperimentAnalysis

    experiments = load_experiments()

    if not experiments:
        print("  Geen experimenten gevonden.")
        print("  Activeer A/B testing via: AB_TESTING_ENABLED=true")
        input("Press Enter to close...")
        return

    print(f"  {len(experiments)} experiment(en) gevonden.\n")

    for exp_id, exp_data in experiments.items():
        analysis = ExperimentAnalysis(exp_data)
        result = analysis.analyze()

        print(f"  ━━━ {exp_id} ━━━")
        print(f"  Status:     {'STOPPEN' if result.should_stop else ('WINNAAR GEVONDEN' if result.winner else 'BEZIG')}")
        print(f"  Steekproef: {result.total_samples} leads")
        print(f"  Niveau:     {result.significance_level}")

        if result.variant_results:
            print(f"\n  {'Variant':<20s} {'N':>6s} {'Convs':>6s} {'Rate':>8s} {'95% CI':>20s} {'Winner':>8s}")
            print(f"  {'-'*20} {'-'*6} {'-'*6} {'-'*8} {'-'*20} {'-'*8}")

            for vr in result.variant_results:
                ci_low = f"{vr.confidence_interval[0]:.1%}" if vr.confidence_interval else "n.v.t."
                ci_high = f"{vr.confidence_interval[1]:.1%}" if vr.confidence_interval else ""
                winner_mark = " ◀ JA" if vr.is_winner else ""
                print(f"  {vr.variant_id:<20s} {vr.sample_size:>6d} {vr.conversions:>6d} {vr.conversion_rate:>7.2%} [{ci_low}, {ci_high}]{winner_mark}")

        if result.winner:
            print(f"\n  👉 WINNAAR: {result.winner} (p={result.p_value:.4f})")
        elif result.should_stop:
            print(f"\n  ⚠️  Geen verschil gevonden bij {result.significance_level} niveau.")
        else:
            print(f"\n  ⏳ Nog niet genoeg data voor significantie (min {result.min_sample_size} per variant gewenst)")

        print("")

    input("Press Enter to close...")


def _show_sequence_overview() -> None:
    """Toon een overzicht van gegenereerde follow-up sequences."""
    from sequence_engine import SequenceResult

    print("")
    print("=== 📬 Follow-up Sequence Overzicht ===")
    print("")

    import glob
    import pandas as pd

    output_dir = Path("data/output")
    recent_files = sorted(glob.glob(str(output_dir / "*_output.*")))
    if not recent_files:
        print("  Geen outputbestanden gevonden.")
        input("Press Enter to close...")
        return

    latest = recent_files[-1]
    try:
        df = pd.read_excel(latest) if latest.endswith(".xlsx") else pd.read_csv(latest)
    except Exception:
        print("  Kan bestand niet lezen.")
        input("Press Enter to close...")
        return

    sequence_cols = [c for c in df.columns if c.startswith("sequence_") or c == "follow_up_type"]
    if not sequence_cols:
        print("  Geen sequence data gevonden in het laatste bestand.")
        print("  Zet FOLLOW_UP_SEQUENCE_ENABLED=true en run opnieuw.")
        input("Press Enter to close...")
        return

    seq_rows = df[df["sequence_step"].notna() & (df["sequence_step"] != "")]
    if seq_rows.empty:
        print("  Geen follow-up sequences gegenereerd.")
        input("Press Enter to close...")
        return

    print(f"  {len(seq_rows)} follow-up entries gevonden in {latest}\n")
    print(f"  {'#':>3s} {'Company':<25s} {'Stap':>5s} {'Type':<15s} {'Opening Line'}")
    print(f"  {'-'*3} {'-'*24} {'-'*5} {'-'*14} {'-'*60}")

    for i, (_, row) in enumerate(seq_rows.head(30).iterrows()):
        step = row.get("sequence_step", "?")
        ftype = row.get("follow_up_type", "?")
        opening = str(row.get("sequence_opening_line", ""))[:58]
        company = str(row.get("company_name", ""))[:23]
        print(f"  {i+1:>3d} {company:<25s} {step:>5s} {ftype:<15s} {opening}")

    input("\nPress Enter to close...")


# ---- Streaming print helper ----
def _print(stream, text, end="\n", flush=False):
    """Print met optionele stream output (voor Streamlit compatibiliteit)."""
    print(text, end=end, flush=flush)
    if stream is not None:
        stream.write(text + end)


# ---- Argparse helpers (gerecycled van bestaande code) ----
def _make_args(input_path: str, output_path: str, campaign_context: str, tone_profile: str,
               max_workers: int = 4, batch_size: int = 50, force: bool = False,
               manual_review: bool = False, skip_research: bool = False) -> Any:
    """Maak een argparse-achtig namespace object."""
    from argparse import Namespace
    return Namespace(
        input=input_path,
        output=output_path,
        campaign_context=campaign_context,
        tone_profile=tone_profile,
        max_workers=max_workers,
        batch_size=batch_size,
        force=force,
        manual_review_mode=manual_review,
        skip_research=skip_research,
        client_batch_output=False,
        sending_tool_preset="",
        sending_tool_output="",
        quiet=False,
        verbose=False,
    )


def _maybe_prompt_for_api_key(settings: Settings) -> Settings:
    """Vraag om een API key als er nog geen is ingesteld."""
    print("Geen API key gevonden. Voer een API key in (of druk Enter om over te slaan):")
    key = input(f"  {settings.llm_provider.upper()} API key: ").strip()
    if key:
        env_var = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }.get(settings.llm_provider, "OPENAI_API_KEY")
        os.environ[env_var] = key
        return load_settings()
    return settings


if __name__ == "__main__":
    main()