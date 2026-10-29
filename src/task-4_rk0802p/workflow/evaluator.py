"""Deterministic fake evaluator for Task 4 review workflow.

Provides predictable fixture-driven evaluation decisions without external
model calls, enabling deterministic routing tests and reproducible branch traversal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from workflow.models import ContentItem, EvaluationDecision, EvaluatorResponse


class EvaluatorProtocol(Protocol):
    """Protocol for content evaluators."""

    def evaluate(self, content: ContentItem, revision_count: int) -> EvaluatorResponse:
        """Evaluate content draft and produce a routing decision."""
        ...


class DeterministicEvaluator:
    """Fixture-driven deterministic evaluator for testing workflow branching."""

    def __init__(
        self,
        responses: Optional[List[EvaluatorResponse | dict[str, Any]]] = None,
        scenario_name: Optional[str] = None,
        fixtures_path: Optional[Path | str] = None,
    ) -> None:
        self.call_history: List[tuple[str, int, EvaluatorResponse]] = []
        self._index: int = 0
        self._responses: List[EvaluatorResponse] = []

        if scenario_name:
            self._load_scenario(scenario_name, fixtures_path)
        elif responses:
            for r in responses:
                if isinstance(r, EvaluatorResponse):
                    self._responses.append(r)
                else:
                    self._responses.append(EvaluatorResponse.model_validate(r))

    def _load_scenario(self, scenario_name: str, fixtures_path: Optional[Path | str]) -> None:
        """Load predetermined responses for a named scenario from JSON fixture."""
        path = (
            Path(fixtures_path)
            if fixtures_path
            else Path(__file__).resolve().parent.parent / "fixtures" / "evaluator_scenarios.json"
        )
        if not path.exists():
            raise FileNotFoundError(f"Fixture file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            scenarios = json.load(f)

        if scenario_name not in scenarios:
            available = list(scenarios.keys())
            raise ValueError(f"Unknown scenario '{scenario_name}'. Available scenarios: {available}")

        for item in scenarios[scenario_name]:
            self._responses.append(EvaluatorResponse.model_validate(item))

    def evaluate(self, content: ContentItem, revision_count: int) -> EvaluatorResponse:
        """Evaluate draft deterministically, returning the next configured response."""
        if not self._responses:
            # Default fallback if no responses configured: route to human review
            response = EvaluatorResponse(
                decision=EvaluationDecision.HUMAN_REVIEW,
                feedback="Default deterministic pass: content ready for human review.",
                score=1.0,
            )
        elif self._index < len(self._responses):
            response = self._responses[self._index]
            self._index += 1
        else:
            # If past the configured sequence, repeat the last response
            response = self._responses[-1]

        self.call_history.append((content.content_id, revision_count, response))
        return response

    def reset(self) -> None:
        """Reset sequence pointer and call history."""
        self._index = 0
        self.call_history.clear()
