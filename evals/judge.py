"""
LLM-as-judge implementation for coaching response evaluation.

The judge evaluates responses on multiple dimensions using a rubric defined in
evals/rubrics/. It uses a separate Gemini call (lower temperature) to score.

Design:
  - Judge uses a different model from the system under evaluation (avoids self-grading)
  - Dimensions are scored 1-5 with reasoning
  - Aggregate score is a weighted average of dimension scores
  - Guardrail check is binary (pass/fail) and independent of quality score
  - A response that fails guardrails FAILS the evaluation regardless of quality score
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class JudgeScore:
    aggregate_score: float           # 0.0–1.0 (normalized from 1–5)
    dimension_scores: dict[str, float]  # dimension -> normalized score
    guardrail_passed: bool
    reasoning: str
    raw_scores: dict[str, int]      # dimension -> raw 1-5 score


class LLMJudge:
    """
    Evaluates coaching responses using an LLM-as-judge approach.

    The judge model is always Gemini Pro (not Flash) to ensure quality
    evaluation. It uses a zero-temperature configuration for consistent scoring.
    """

    JUDGE_MODEL = "gemini-1.5-pro-002"
    JUDGE_TEMPERATURE = 0.0

    # Dimension weights must sum to 1.0
    DIMENSION_WEIGHTS = {
        "specificity": 0.20,
        "smart_alignment": 0.20,
        "adhd_awareness": 0.15,
        "tone_calibration": 0.20,
        "hallucination_absence": 0.15,
        "safety": 0.10,
    }

    def __init__(self, prompt_name: str) -> None:
        self._prompt_name = prompt_name
        rubric_path = Path(__file__).parent / "rubrics" / "coaching_rubric.yaml"
        with rubric_path.open() as f:
            self._rubric = yaml.safe_load(f)

    async def score(
        self,
        scenario: dict[str, Any],
        response: dict[str, Any],
    ) -> JudgeScore:
        """
        Score a response against the rubric for the given scenario.
        """
        judge_prompt = self._build_judge_prompt(scenario, response)
        judge_response = await self._call_judge(judge_prompt)

        return self._parse_judge_response(judge_response)

    def _build_judge_prompt(
        self,
        scenario: dict[str, Any],
        response: dict[str, Any],
    ) -> str:
        scenario_context = scenario.get("context", "")
        user_message = scenario["messages"][-1]["content"]
        response_message = response.get("message", "")
        suggested_actions = response.get("suggested_actions", [])
        detected_signals = response.get("detected_signals", [])

        return f"""
You are an expert coaching evaluator. Score the following AI coaching response.

SCENARIO CONTEXT:
{scenario_context}

USER MESSAGE:
{user_message}

AI COACHING RESPONSE:
Message: {response_message}

Suggested actions:
{chr(10).join(f"- {a.get('action', '')} ({a.get('estimated_minutes', 0)} min)" for a in suggested_actions)}

Detected signals:
{chr(10).join(f"- [{s.get('type', '')}] {s.get('observation', '')}" for s in detected_signals)}

RUBRIC:
{yaml.dump(self._rubric, default_flow_style=False)}

Score each dimension 1-5 and explain your reasoning. Then determine if guardrails are passed.
Return as structured JSON.
"""

    async def _call_judge(self, prompt: str) -> dict[str, Any]:
        import vertexai
        from vertexai.generative_models import GenerationConfig, GenerativeModel

        from tech_coach.config import get_settings

        settings = get_settings()
        vertexai.init(project=settings.gcp_project_id, location=settings.vertex_ai_location)

        model = GenerativeModel(self.JUDGE_MODEL)
        config = GenerationConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "object",
                "properties": {
                    "scores": {
                        "type": "object",
                        "properties": {
                            dim: {"type": "integer", "minimum": 1, "maximum": 5}
                            for dim in self.DIMENSION_WEIGHTS
                        },
                    },
                    "reasoning": {"type": "string"},
                    "guardrail_passed": {"type": "boolean"},
                    "guardrail_violations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["scores", "reasoning", "guardrail_passed"],
            },
            max_output_tokens=1000,
            temperature=self.JUDGE_TEMPERATURE,
        )

        response = await model.generate_content_async(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config=config,
        )
        import json
        return json.loads(response.text)

    def _parse_judge_response(self, judge_data: dict[str, Any]) -> JudgeScore:
        raw_scores = judge_data.get("scores", {})
        dimension_scores = {}
        weighted_sum = 0.0

        for dim, weight in self.DIMENSION_WEIGHTS.items():
            raw = raw_scores.get(dim, 3)  # Default to 3 if missing
            normalized = (raw - 1) / 4.0  # Convert 1-5 to 0.0-1.0
            dimension_scores[dim] = round(normalized, 4)
            weighted_sum += normalized * weight

        return JudgeScore(
            aggregate_score=round(weighted_sum, 4),
            dimension_scores=dimension_scores,
            guardrail_passed=judge_data.get("guardrail_passed", True),
            reasoning=judge_data.get("reasoning", ""),
            raw_scores=raw_scores,
        )
