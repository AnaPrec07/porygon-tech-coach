"""
Per-request cost estimation utility.

Pricing is configured via settings (updated when Vertex AI pricing changes).
All estimates are in USD. Cost is logged per call and summed at session level.
"""

from __future__ import annotations

from dataclasses import dataclass

from tech_coach.config import get_settings


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
    model_id: str


class CostEstimator:
    """
    Estimates Vertex AI Gemini API costs.

    Pricing is read from settings so it can be updated without code changes.
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def estimate(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> CostEstimate:
        """
        Estimate cost for a single Vertex AI call.

        Pricing is per 1k tokens. Uses "pro" pricing by default;
        "flash" pricing for flash-tier models.
        """
        settings = self._settings
        is_flash = "flash" in model_id.lower()

        input_price = (
            settings.gemini_flash_input_price_per_1k
            if is_flash
            else settings.gemini_pro_input_price_per_1k
        )
        output_price = (
            settings.gemini_flash_output_price_per_1k
            if is_flash
            else settings.gemini_pro_output_price_per_1k
        )

        input_cost = (input_tokens / 1000.0) * input_price
        output_cost = (output_tokens / 1000.0) * output_price

        return CostEstimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost_usd=round(input_cost, 8),
            output_cost_usd=round(output_cost, 8),
            total_cost_usd=round(input_cost + output_cost, 8),
            model_id=model_id,
        )
