"""Impact analyzer — vertaalt feedback-patronen naar LLM-context hints.

Analyseert historische send-feedback om te bepalen welke angles,
friction types en evidence combinaties het beste converteren.
Deze inzichten worden als extra context meegestuurd naar de
write_personalization en qc_personalization prompts.
"""
from __future__ import annotations

from typing import Any

from feedback import get_failing_patterns, get_feedback_summary, get_success_patterns


def build_feedback_context(feedback_limit: int = 20) -> str:
    """Bouwt een tekstblok met feedback-geleide hints voor de LLM.

    Dit wordt als extra sectie in de user-prompt geinjecteerd,
    zodat het model kan leren van eerdere sends.
    """
    summary = get_feedback_summary()
    if summary["total_sends"] == 0:
        return ""

    success_patterns = get_success_patterns(limit=feedback_limit)
    failing_patterns = get_failing_patterns(limit=feedback_limit)

    lines: list[str] = []
    lines.append("")
    lines.append("--- FEEDBACK FROM PREVIOUS SENDS ---")
    lines.append("")

    # Overzicht
    lines.append("OVERVIEW:")
    lines.append(f"  Total sends: {summary['total_sends']}")
    lines.append(f"  Open rate: {summary['open_rate']}%")
    lines.append(f"  Reply rate: {summary['reply_rate']}%")
    lines.append(f"  Conversion rate: {summary['conversion_rate']}%")
    lines.append(f"  Average reply time: {summary['avg_reply_time_minutes']} min")
    lines.append("")

    # Wat werkt
    if success_patterns:
        lines.append("WHAT WORKS (high-converting patterns):")
        for p in success_patterns[:5]:
            angle = p.get("chosen_angle", "unknown")
            conv_rate = p.get("conv_rate", 0)
            n = p.get("times_used", 0)
            if angle and n >= 1:
                lines.append(f"  - Angle \"{angle}\": {conv_rate}% conv rate ({n} sends)")
                example_lines = p.get("example_opening_lines", "")
                if example_lines:
                    # Toon max 2 voorbeeld openingszinnen
                    examples = [l.strip() for l in str(example_lines).split("|") if l.strip()][:2]
                    for ex in examples:
                        lines.append(f"      Ex: \"{ex[:100]}\"")
        lines.append("")

    # Wat niet werkt
    if failing_patterns:
        lines.append("WHAT DOES NOT WORK (patterns with 0 conversions):")
        for p in failing_patterns[:5]:
            angle = p.get("chosen_angle", "unknown")
            n = p.get("times_used", 0)
            if angle and n >= 2:
                lines.append(f"  - Angle \"{angle}\" ({n} sends, 0 conversions — avoid this angle)")
        lines.append("")

    # Per friction type
    by_friction = summary.get("by_friction_type", [])
    if by_friction:
        lines.append("CONVERSION BY FRICTION TYPE:")
        for entry in by_friction[:5]:
            ft = entry.get("friction_type", "unknown")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            lines.append(f"  - {ft}: {cr}% conv rate ({n} sends)")
        lines.append("")

    # Per angle category
    by_angle = summary.get("by_angle_category", [])
    if by_angle:
        lines.append("CONVERSION BY ANGLE CATEGORY:")
        for entry in by_angle[:5]:
            ac = entry.get("angle_category", "unknown")
            cr = entry.get("conversion_rate", 0)
            n = entry.get("total", 0)
            lines.append(f"  - {ac}: {cr}% conv rate ({n} sends)")
        lines.append("")

    hints = []
    if success_patterns:
        top = success_patterns[0]
        if top.get("chosen_angle"):
            hints.append(f"Best performing angle historically: \"{top['chosen_angle']}\"")
        if top.get("friction_type"):
            hints.append(f"Best performing friction type: \"{top['friction_type']}\"")
        if top.get("surface_checked"):
            hints.append(f"Best performing surface: \"{top['surface_checked']}\"")

    if failing_patterns:
        failing_angles = [p["chosen_angle"] for p in failing_patterns if p.get("chosen_angle")]
        if failing_angles:
            hints.append(f"Avoid these angles (0% conversion): {', '.join(failing_angles[:3])}")

    if hints:
        lines.append("GUIDANCE:")
        for h in hints:
            lines.append(f"  - {h}")
        lines.append("")

    return "\n".join(lines)