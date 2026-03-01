"""Evaluation report aggregation and serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EvalReport:
    prompt_name: str
    version: str
    threshold: float
    results: list[dict[str, Any]]
    evaluated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def aggregate_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r["score"] for r in self.results) / len(self.results)

    @property
    def guardrail_pass_rate(self) -> float:
        if not self.results:
            return 0.0
        passed = sum(1 for r in self.results if r.get("guardrail_passed", True))
        return passed / len(self.results)

    @property
    def passed(self) -> bool:
        return (
            self.aggregate_score >= self.threshold
            and self.guardrail_pass_rate == 1.0  # All guardrails must pass
        )

    @property
    def per_dimension_averages(self) -> dict[str, float]:
        if not self.results:
            return {}
        dims: dict[str, list[float]] = {}
        for result in self.results:
            for dim, score in result.get("dimension_scores", {}).items():
                dims.setdefault(dim, []).append(score)
        return {dim: sum(scores) / len(scores) for dim, scores in dims.items()}

    @property
    def failed_scenarios(self) -> list[dict]:
        return [r for r in self.results if r["score"] < self.threshold]

    def to_json(self) -> str:
        return json.dumps(
            {
                "prompt_name": self.prompt_name,
                "version": self.version,
                "threshold": self.threshold,
                "aggregate_score": round(self.aggregate_score, 4),
                "guardrail_pass_rate": round(self.guardrail_pass_rate, 4),
                "passed": self.passed,
                "evaluated_at": self.evaluated_at.isoformat(),
                "per_dimension_averages": {
                    k: round(v, 4) for k, v in self.per_dimension_averages.items()
                },
                "scenario_count": len(self.results),
                "failed_scenario_count": len(self.failed_scenarios),
                "results": self.results,
            },
            indent=2,
        )

    def print_summary(self) -> None:
        print(f"\nEvaluation Report: {self.prompt_name} v{self.version}")
        print(f"  Aggregate score: {self.aggregate_score:.2%}")
        print(f"  Threshold:       {self.threshold:.0%}")
        print(f"  Guardrails:      {self.guardrail_pass_rate:.0%} pass rate")
        print(f"  Result:          {'PASSED ✓' if self.passed else 'FAILED ✗'}")
        print("\n  Dimension averages:")
        for dim, score in sorted(self.per_dimension_averages.items()):
            bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
            print(f"    {dim:<25} {bar} {score:.2%}")
        if self.failed_scenarios:
            print(f"\n  Failed scenarios ({len(self.failed_scenarios)}):")
            for s in self.failed_scenarios:
                print(f"    - {s['scenario_id']}: {s['score']:.2%}")
