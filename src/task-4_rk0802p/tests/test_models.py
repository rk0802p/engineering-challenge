"""Tests for typed workflow contracts and models (Phase 1).

Acceptance check:
- Invalid content fails validation before graph execution begins.
- Unknown evaluator decisions fail validation.
- WorkflowState and WorkflowEvent conform strictly to contracts.
"""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from workflow.models import (
    ContentItem,
    EvaluationDecision,
    EvaluatorResponse,
    EventType,
    WorkflowEvent,
    WorkflowStatus,
    WorkflowState,
    validate_workflow_input,
)


class TestContentItemValidation:
    """Validate ContentItem schema and constraints."""

    def test_valid_content_item(self):
        item = ContentItem(
            content_id="content-001",
            title="Valid Title",
            body="Valid content body text.",
            metadata={"source": "unit_test"},
        )
        assert item.content_id == "content-001"
        assert item.title == "Valid Title"
        assert item.body == "Valid content body text."
        assert item.metadata == {"source": "unit_test"}

    def test_content_item_strips_whitespace(self):
        item = ContentItem(
            content_id="  content-001  ",
            title="  Title with spaces  ",
            body="  Body with spaces  ",
        )
        assert item.content_id == "content-001"
        assert item.title == "Title with spaces"
        assert item.body == "Body with spaces"

    @pytest.mark.parametrize(
        "empty_val",
        ["", "   ", "\t\n"],
    )
    def test_rejects_empty_or_whitespace_fields(self, empty_val):
        with pytest.raises(ValidationError) as exc:
            ContentItem(content_id=empty_val, title="Title", body="Body")
        assert "content_id" in str(exc.value)

        with pytest.raises(ValidationError) as exc:
            ContentItem(content_id="c1", title=empty_val, body="Body")
        assert "title" in str(exc.value)

        with pytest.raises(ValidationError) as exc:
            ContentItem(content_id="c1", title="Title", body=empty_val)
        assert "body" in str(exc.value)

    def test_rejects_missing_required_fields(self):
        with pytest.raises(ValidationError):
            ContentItem.model_validate({"title": "No ID", "body": "Body"})

        with pytest.raises(ValidationError):
            ContentItem.model_validate({"content_id": "c1", "body": "Body"})

        with pytest.raises(ValidationError):
            ContentItem.model_validate({"content_id": "c1", "title": "Title"})

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError) as exc:
            ContentItem.model_validate(
                {
                    "content_id": "c1",
                    "title": "Title",
                    "body": "Body",
                    "unauthorized_field": "injected",
                }
            )
        assert "extra_forbidden" in str(exc.value)


class TestEvaluatorResponseValidation:
    """Validate EvaluatorResponse and EvaluationDecision schema."""

    def test_valid_evaluator_decisions(self):
        res1 = EvaluatorResponse(
            decision=EvaluationDecision.REVISE,
            feedback="Needs editing",
            score=0.6,
        )
        assert res1.decision == EvaluationDecision.REVISE
        assert res1.score == 0.6

        res2 = EvaluatorResponse(
            decision=EvaluationDecision.HUMAN_REVIEW,
            feedback="Ready for review",
            score=0.95,
        )
        assert res2.decision == EvaluationDecision.HUMAN_REVIEW

    def test_parses_string_decision_case_insensitive(self):
        res = EvaluatorResponse(decision="revise")
        assert res.decision == EvaluationDecision.REVISE

        res_upper = EvaluatorResponse(decision="HUMAN_REVIEW")
        assert res_upper.decision == EvaluationDecision.HUMAN_REVIEW

    @pytest.mark.parametrize(
        "invalid_decision",
        ["publish", "reject", "approve", "auto_pass", "123", "", "unknown"],
    )
    def test_rejects_unknown_evaluator_decision(self, invalid_decision):
        with pytest.raises(ValidationError) as exc:
            EvaluatorResponse(decision=invalid_decision)
        assert "Unknown evaluator decision" in str(exc.value)

    def test_rejects_out_of_bounds_score(self):
        with pytest.raises(ValidationError):
            EvaluatorResponse(decision="revise", score=1.5)

        with pytest.raises(ValidationError):
            EvaluatorResponse(decision="revise", score=-0.1)

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            EvaluatorResponse.model_validate(
                {"decision": "revise", "injected_param": True}
            )


class TestWorkflowEventValidation:
    """Validate WorkflowEvent schema."""

    def test_valid_workflow_event(self):
        evt = WorkflowEvent(
            run_id="run-001",
            content_id="content-001",
            event_type=EventType.EVALUATION_COMPLETED,
            stage="evaluation",
            revision_count=0,
            payload={"decision": "human_review"},
        )
        assert evt.run_id == "run-001"
        assert evt.content_id == "content-001"
        assert evt.event_type == EventType.EVALUATION_COMPLETED
        assert evt.event_id.startswith("evt_")
        assert isinstance(evt.timestamp, datetime)

    def test_rejects_unknown_event_type(self):
        with pytest.raises(ValidationError) as exc:
            WorkflowEvent(
                run_id="run-001",
                content_id="content-001",
                event_type="invalid_event_type",
                stage="evaluation",
            )
        assert "Unknown event type" in str(exc.value)


class TestWorkflowStateAndInputValidation:
    """Validate workflow input validation before execution."""

    def test_valid_input_dict_creates_workflow_state(self):
        raw_input = {
            "run_id": "run-100",
            "content_id": "content-001",
            "content": {
                "content_id": "content-001",
                "title": "Report Title",
                "body": "Report body text.",
            },
        }
        state = validate_workflow_input(raw_input)
        assert state.run_id == "run-100"
        assert state.content_id == "content-001"
        assert state.content.title == "Report Title"
        assert state.status == WorkflowStatus.PENDING
        assert state.revision_count == 0
        assert state.max_revisions == 2

    def test_validate_input_rejects_malformed_content(self):
        # Missing required body in content item
        malformed_input = {
            "run_id": "run-100",
            "content_id": "content-001",
            "content": {
                "content_id": "content-001",
                "title": "Title with no body",
            },
        }
        with pytest.raises(ValidationError) as exc:
            validate_workflow_input(malformed_input)
        assert "body" in str(exc.value)

    def test_validate_input_rejects_missing_content(self):
        malformed_input = {
            "run_id": "run-100",
            "content_id": "content-001",
        }
        with pytest.raises(ValidationError) as exc:
            validate_workflow_input(malformed_input)
        assert "content" in str(exc.value)

    def test_validate_input_rejects_non_dict(self):
        with pytest.raises(TypeError):
            validate_workflow_input("not a dict")
