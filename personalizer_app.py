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
    print("Kies een optie:")
    print("  [1] Nieuwe personalisatie-run starten")
    print("  [2] Feedback invoeren (open/reply/conversion resultaten)")
    print("  [3] Feedback dashboard bekijken")
    choice = input("Optie [1/2/3]: ").strip()

    if choice == "2":
        _feed_back_results()
        return
    elif choice == "3":
        _show_feedback_dashboard()
        return
    # Standaard: run 1 (nieuwe personalisatie)

    from feedback import init_feedback_db
    init_feedback_db()

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


def _feed_back_results() -> None:
    """Interactieve feedback-invoer: voer open/reply/conversion resultaten in."""
    from feedback import (
        SendFeedback,
        load_feedback,
        get_feedback_summary,
        ingest_feedback_results,
    )

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

    # Toon beschikbare records die nog geen feedback hebben
    all_feedback = load_feedback(run_id)
    pending = [fb for fb in all_feedback if not fb.was_opened and not fb.got_reply and not fb.converted]

    if not pending:
        print("Alle records voor deze run hebben al feedback.")

        # Toon samenvatting
        summary = get_feedback_summary()
        print("")
        print("=== Huidige Samenvatting ===")
        print(f"  Totale sends:    {summary['total_sends']}")
        print(f"  Open rate:       {summary['open_rate']}%")
        print(f"  Reply rate:      {summary['reply_rate']}%")
        print(f"  Conversie rate:  {summary['conversion_rate']}%")
        print(f"  Avg reply tijd:  {summary['avg_reply_time_minutes']} min")
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


def _feed_back_interactive(run_id: str, all_feedback) -> None:
    result_rows: list[dict[str, Any]] = []
    for fb in all_feedback:
        print("")
        print(f"--- {fb.company_name} ({fb.recipient_name}, {fb.recipient_role}) ---")
        print(f"  Opening line: {fb.opening_line[:80]}...")
        print(f"  Angle: {fb.chosen_angle}")

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


def _feed_back_bulk(run_id: str, all_feedback) -> None:
    """Bulk feedback invoer via een eenvoudig interactief proces."""
    # Maak een mapping van example_id -> feedback record
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
    from feedback import get_feedback_summary

    summary = get_feedback_summary()
    print("")
    print("=== Bijgewerkte Samenvatting ===")
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
            print(f"    - {ft}: {cr}% conv ({n} sends)")


def _show_feedback_dashboard() -> None:
    """Toon het feedback dashboard."""
    from feedback import get_feedback_summary, get_success_patterns, get_failing_patterns

    print("")
    print("=== Feedback Dashboard ===")

    summary = get_feedback_summary()
    print(f"\n  Totale sends:    {summary['total_sends']}")
    print(f"  Open rate:       {summary['open_rate']}%")
    print(f"  Reply rate:      {summary['reply_rate']}%")
    print(f"  Conversie rate:  {summary['conversion_rate']}%")
    print(f"  Avg reply tijd:  {summary['avg_reply_time_minutes']} min")

    if summary["total_sends"] == 0:
        print("\n  Nog geen feedback data beschikbaar.")
        input("Press Enter to close...")
        return

    if summary["by_friction_type"]:
        print("\n  === Per Friction Type ===")
        for entry in summary["by_friction_type"]:
            ft = entry.get("friction_type", "onbekend")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            bar = "█" * int(cr / 5) + "░" * (20 - int(cr / 5))
            print(f"    {ft:35s} {bar} {cr:5.1f}% ({n} sends)")

    if summary["by_angle_category"]:
        print("\n  === Per Angle Category ===")
        for entry in summary["by_angle_category"]:
            ac = entry.get("angle_category", "onbekend")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            bar = "█" * int(cr / 5) + "░" * (20 - int(cr / 5))
            print(f"    {ac:35s} {bar} {cr:5.1f}% ({n} sends)")

    success = get_success_patterns(limit=5)
    if success:
        print("\n  === Wat Werkt ===")
        for p in success:
            angle = p.get("chosen_angle", "unknown")
            conv = p.get("conv_rate", 0)
            n = p.get("times_used", 0)
            print(f"    + {angle} → {conv}% conv ({n}x)")

    failing = get_failing_patterns(limit=5)
    if failing:
        print("\n  === Wat Niet Werkt ===")
        for p in failing:
            angle = p.get("chosen_angle", "unknown")
            n = p.get("times_used", 0)
            print(f"    - {angle} ({n}x, 0% conv)")

    print("")
    input("Press Enter to close...")