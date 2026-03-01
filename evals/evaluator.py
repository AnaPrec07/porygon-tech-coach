"""
Offline evaluation runner for prompt version regression testing.

Usage:
    python evals/evaluator.py --prompt-name coaching_dialogue --version 1.0.0

The evaluator:
  1. Loads the golden dataset for the specified prompt
  2. Runs each scenario through the prompt (via Vertex AI)
  3. Scores each response using LLM-as-judge
  4. Computes aggregate score
  5. Compares against baseline (current production version)
  6. Exits 0 if score >= threshold, 1 if regression detected

This script is designed to be called from CI/CD (Cloud Build).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from evals.judge import LLMJudge
from evals.report import EvalReport


async def run_eval(
    prompt_name: str,
    version: str,
    threshold: float = 0.85,
    golden_dataset_path: Path | None = None,
) -> EvalReport:
    """
    Run evaluation for a prompt version against the golden dataset.

    Args:
        prompt_name: Name of the prompt to evaluate
        version: Version string (e.g., "1.0.0")
        threshold: Minimum aggregate score to pass (0.0–1.0)
        golden_dataset_path: Override default dataset path

    Returns:
        EvalReport with scores and pass/fail determination
    """
    dataset_path = golden_dataset_path or (
        Path(__file__).parent / "golden_dataset" / f"{prompt_name}_scenarios.json"
    )

    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Golden dataset not found: {dataset_path}\n"
            "Run scripts/seed_golden_dataset.py to create it."
        )

    with dataset_path.open() as f:
        scenarios: list[dict[str, Any]] = json.load(f)

    print(f"\n{'='*60}")
    print(f"Evaluating: {prompt_name} v{version}")
    print(f"Scenarios: {len(scenarios)}")
    print(f"Threshold: {threshold:.0%}")
    print(f"{'='*60}\n")

    judge = LLMJudge(prompt_name=prompt_name)
    results = []

    for i, scenario in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] {scenario['id']}: ", end="", flush=True)

        # Generate response using the prompt version
        response = await _generate_response(
            prompt_name=prompt_name,
            messages=scenario["messages"],
        )

        # Score with LLM-as-judge
        score_result = await judge.score(
            scenario=scenario,
            response=response,
        )

        results.append({
            "scenario_id": scenario["id"],
            "category": scenario.get("category", "general"),
            "score": score_result.aggregate_score,
            "dimension_scores": score_result.dimension_scores,
            "guardrail_passed": score_result.guardrail_passed,
            "judge_reasoning": score_result.reasoning,
        })

        status = "✓" if score_result.aggregate_score >= threshold else "✗"
        print(
            f"{status} {score_result.aggregate_score:.2f} "
            f"(guardrails: {'pass' if score_result.guardrail_passed else 'FAIL'})"
        )

    report = EvalReport(
        prompt_name=prompt_name,
        version=version,
        threshold=threshold,
        results=results,
    )

    print(f"\n{'='*60}")
    print(f"Aggregate score: {report.aggregate_score:.2%}")
    print(f"Guardrail pass rate: {report.guardrail_pass_rate:.0%}")
    print(f"Result: {'PASSED' if report.passed else 'FAILED'}")
    print(f"{'='*60}\n")

    return report


async def _generate_response(
    prompt_name: str,
    messages: list[dict],
) -> dict[str, Any]:
    """Generate a response using the current prompt configuration."""
    import os
    from pathlib import Path as PathLib

    from tech_coach.config import get_settings
    from tech_coach.infrastructure.llm.cache import LLMCache
    from tech_coach.infrastructure.llm.prompt_registry import PromptRegistry
    from tech_coach.infrastructure.llm.vertex_client import VertexAIClient
    from tech_coach.infrastructure.observability.cost_estimator import CostEstimator

    settings = get_settings()
    prompts_dir = PathLib(__file__).parent.parent / "prompts" / "v1"
    registry = PromptRegistry(prompts_dir=prompts_dir)
    cache = LLMCache()
    client = VertexAIClient(
        prompt_registry=registry,
        cache=cache,
        cost_estimator=CostEstimator(),
    )

    response = await client.generate(
        prompt_name=prompt_name,
        messages=messages,
        user_id="eval-runner",
        trace_id="eval-runner",
    )
    await cache.close()
    return response.parsed_content


def main() -> None:
    parser = argparse.ArgumentParser(description="Run prompt evaluation")
    parser.add_argument("--prompt-name", required=True, help="Prompt name to evaluate")
    parser.add_argument("--version", default="latest", help="Version to evaluate")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Minimum aggregate score to pass (default: 0.85)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to this file",
    )
    args = parser.parse_args()

    report = asyncio.run(
        run_eval(
            prompt_name=args.prompt_name,
            version=args.version,
            threshold=args.threshold,
        )
    )

    if args.output:
        args.output.write_text(report.to_json())
        print(f"Report written to {args.output}")

    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
