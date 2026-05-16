from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MODEL_PRICE_PRESETS_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "deepseek-chat": (0.27, 1.10),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
}


@dataclass(frozen=True)
class CostEstimate:
    llm_calls: int
    input_tokens: int
    output_tokens: int
    input_price_per_1m: float
    output_price_per_1m: float
    estimated_cost_usd: float
    cost_per_row_usd: float


def price_for_model(model_name: str) -> tuple[float, float]:
    normalized = str(model_name or "").strip().lower()
    return MODEL_PRICE_PRESETS_USD_PER_1M.get(normalized, (0.10, 0.40))


def _max_int(rows: list[dict[str, Any]], key: str) -> int:
    values: list[int] = []
    for row in rows:
        try:
            values.append(int(float(row.get(key, 0) or 0)))
        except (TypeError, ValueError):
            continue
    return max(values) if values else 0


def estimate_batch_cost(
    rows: list[dict[str, Any]],
    input_price_per_1m: float,
    output_price_per_1m: float,
) -> CostEstimate:
    input_tokens = _max_int(rows, "estimated_input_tokens")
    output_tokens = _max_int(rows, "estimated_output_tokens")
    llm_calls = _max_int(rows, "llm_calls")
    estimated_cost = (input_tokens / 1_000_000 * input_price_per_1m) + (
        output_tokens / 1_000_000 * output_price_per_1m
    )
    row_count = max(1, len(rows))
    return CostEstimate(
        llm_calls=llm_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_price_per_1m=input_price_per_1m,
        output_price_per_1m=output_price_per_1m,
        estimated_cost_usd=estimated_cost,
        cost_per_row_usd=estimated_cost / row_count,
    )
