"""Test validation failures and malformed input handling (Task 4 Required Checks).

Specification check:
- Missing or invalid required fields cause a predictable validation error.
- The workflow should not start processing an invalid content item as though it were valid.
- Unknown evaluator decisions fail validation cleanly.
"""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from workflow.models import (
    ContentItem,
    EvaluatorResponse,
    WorkflowState,
    validate_workflow_input,
)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def content_fixtures(fixtures_dir: Path) -> dict:
    with open(fixtures_dir / "content.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def evaluator_fixtures(fixtures_dir: Path) -> dict:
    with open(fixtures_dir / "evaluator_scenarios.json", "r", encoding="utf-8") as f:
        return json.load(f)


class TestMalformedInputFailures:
    """Verify that incomplete or invalid inputs raise clear validation errors."""

    def test_fixture_missing_content_id(self, content_fixtures):
        fixture = content_fixtures["content-malformed-missing-id"]
        with pytest.raises(ValidationError) as exc:
            ContentItem.model_validate(fixture)
        assert "content_id" in str(exc.value)

    def test_fixture_empty_body(self, content_fixtures):
        fixture = content_fixtures["content-malformed-empty-body"]
        with pytest.raises(ValidationError) as exc:
            ContentItem.model_validate(fixture)
        assert "body" in str(exc.value)

    def test_workflow_input_validation_prevents_execution_on_invalid_data(self, content_fixtures):
        raw_state = {
            "run_id": "run-fail-001",
            "content_id": "bad-item",
            "content": content_fixtures["content-malformed-missing-id"],
        }
        with pytest.raises(ValidationError) as exc:
            validate_workflow_input(raw_state)
        assert "content_id" in str(exc.value)


class TestEvaluatorDecisionFailures:
    """Verify that unknown or invalid evaluator decisions are rejected."""

    def test_fixture_invalid_decision(self, evaluator_fixtures):
        scenario = evaluator_fixtures["invalid_decision"]
        with pytest.raises(ValidationError) as exc:
            EvaluatorResponse.model_validate(scenario[0])
        assert "Unknown evaluator decision" in str(exc.value)

    def test_evaluator_decision_case_handling(self):
        # Invalid decision variants
        for bad in ["REJECT", "approve", "done", "pass", "fail"]:
            with pytest.raises(ValidationError) as exc:
                EvaluatorResponse(decision=bad)
            assert "Unknown evaluator decision" in str(exc.value)
