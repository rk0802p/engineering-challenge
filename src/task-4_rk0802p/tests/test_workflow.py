"""Automated tests for LangGraph review workflow (Phase 2).

Verifies:
- Normal pass to human review and completion.
- One revision then pass sequence (eval -> revise -> eval -> human_review -> complete).
- Bounded revision loop stops predictably after max revisions (2 attempts).
- Event log faithfully records every node execution and decision.
- Conditional routing takes expected branch for each decision.
"""

from pathlib import Path
import pytest

from workflow.evaluator import DeterministicEvaluator
from workflow.events import EventLogger
from workflow.graph import create_review_workflow, route_after_evaluation
from workflow.models import (
    ContentItem,
    EvaluationDecision,
    EventType,
    WorkflowState,
    WorkflowStatus,
)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def base_content() -> ContentItem:
    return ContentItem(
        content_id="content-001",
        title="Quarterly Technical Report Q3",
        body="This report details architectural improvements made to the core pipeline.",
        metadata={"category": "technical_report"},
    )


class TestConditionalRouting:
    """Test graph routing logic based on evaluation decisions and revision limits."""

    def test_routes_to_human_review_on_positive_eval(self, base_content):
        state = WorkflowState(
            run_id="r1",
            content_id=base_content.content_id,
            content=base_content,
            evaluation_result=EvaluationDecision.HUMAN_REVIEW,
            revision_count=0,
            max_revisions=2,
        )
        assert route_after_evaluation(state) == "human_review"

    def test_routes_to_revise_when_under_limit(self, base_content):
        state = WorkflowState(
            run_id="r1",
            content_id=base_content.content_id,
            content=base_content,
            evaluation_result=EvaluationDecision.REVISE,
            revision_count=0,
            max_revisions=2,
        )
        assert route_after_evaluation(state) == "revise"

        state.revision_count = 1
        assert route_after_evaluation(state) == "revise"

    def test_routes_to_limit_reached_when_limit_hit(self, base_content):
        state = WorkflowState(
            run_id="r1",
            content_id=base_content.content_id,
            content=base_content,
            evaluation_result=EvaluationDecision.REVISE,
            revision_count=2,
            max_revisions=2,
        )
        assert route_after_evaluation(state) == "revision_limit_reached"

        state.revision_count = 3
        assert route_after_evaluation(state) == "revision_limit_reached"


class TestNormalPassWorkflow:
    """Verify clean single-pass evaluation reaching human review and approval."""

    def test_normal_pass_reaches_checkpoint_and_completes(self, base_content, fixtures_dir):
        evaluator = DeterministicEvaluator(
            scenario_name="normal_pass",
            fixtures_path=fixtures_dir / "evaluator_scenarios.json",
        )
        logger = EventLogger()
        graph = create_review_workflow(evaluator=evaluator, event_logger=logger)

        initial_state = WorkflowState(
            run_id="run-normal-pass",
            content_id=base_content.content_id,
            content=base_content,
        )
        config = {"configurable": {"thread_id": "run-normal-pass"}}

        # Step 1: Execute graph until human-review pause
        paused_state = graph.invoke(initial_state, config=config)
        assert paused_state["status"] == WorkflowStatus.HUMAN_REVIEW
        assert paused_state["revision_count"] == 0
        assert paused_state["evaluation_result"] == EvaluationDecision.HUMAN_REVIEW

        events_before_approval = logger.get_events("run-normal-pass")
        event_types_before = [e.event_type for e in events_before_approval]
        assert event_types_before == [
            EventType.EVALUATION_COMPLETED,
            EventType.HUMAN_REVIEW_REQUIRED,
            EventType.CHECKPOINT_SAVED,
        ]

        # Step 2: Resume after approval
        completed_state = graph.invoke(None, config=config)
        assert completed_state["status"] == WorkflowStatus.COMPLETED

        all_events = logger.get_events("run-normal-pass")
        all_event_types = [e.event_type for e in all_events]
        assert all_event_types == [
            EventType.EVALUATION_COMPLETED,
            EventType.HUMAN_REVIEW_REQUIRED,
            EventType.CHECKPOINT_SAVED,
            EventType.HUMAN_APPROVED,
            EventType.WORKFLOW_COMPLETED,
        ]


class TestOneRevisionThenPassWorkflow:
    """Verify single revision loop followed by approval."""

    def test_one_revision_then_pass(self, base_content, fixtures_dir):
        evaluator = DeterministicEvaluator(
            scenario_name="one_revision_then_pass",
            fixtures_path=fixtures_dir / "evaluator_scenarios.json",
        )
        logger = EventLogger()
        graph = create_review_workflow(evaluator=evaluator, event_logger=logger)

        initial_state = WorkflowState(
            run_id="run-one-revision",
            content_id=base_content.content_id,
            content=base_content,
        )
        config = {"configurable": {"thread_id": "run-one-revision"}}

        # Step 1: Run until human review boundary
        paused_state = graph.invoke(initial_state, config=config)
        assert paused_state["status"] == WorkflowStatus.HUMAN_REVIEW
        assert paused_state["revision_count"] == 1
        assert "Revision 1" in paused_state["content"].body

        # Verify full sequence of events before review
        events_before = [e.event_type for e in logger.get_events("run-one-revision")]
        assert events_before == [
            EventType.EVALUATION_COMPLETED,  # 1st eval (decision: revise)
            EventType.REVISION_REQUESTED,
            EventType.REVISION_COMPLETED,
            EventType.EVALUATION_COMPLETED,  # 2nd eval (decision: human_review)
            EventType.HUMAN_REVIEW_REQUIRED,
            EventType.CHECKPOINT_SAVED,
        ]

        # Step 2: Resume and approve
        completed_state = graph.invoke(None, config=config)
        assert completed_state["status"] == WorkflowStatus.COMPLETED

        events_after = [e.event_type for e in logger.get_events("run-one-revision")]
        assert events_after[-2:] == [
            EventType.HUMAN_APPROVED,
            EventType.WORKFLOW_COMPLETED,
        ]


class TestRevisionLimitWorkflow:
    """Verify that repeated revision requests terminate at maximum 2 revisions."""

    def test_stops_after_two_revisions(self, base_content, fixtures_dir):
        evaluator = DeterministicEvaluator(
            scenario_name="always_revise",
            fixtures_path=fixtures_dir / "evaluator_scenarios.json",
        )
        logger = EventLogger()
        graph = create_review_workflow(evaluator=evaluator, event_logger=logger)

        initial_state = WorkflowState(
            run_id="run-always-revise",
            content_id=base_content.content_id,
            content=base_content,
            max_revisions=2,
        )
        config = {"configurable": {"thread_id": "run-always-revise"}}

        terminal_state = graph.invoke(initial_state, config=config)

        # Must terminate in REVISION_LIMIT_REACHED with exactly 2 revisions
        assert terminal_state["status"] == WorkflowStatus.REVISION_LIMIT_REACHED
        assert terminal_state["revision_count"] == 2
        assert "Maximum revision attempts (2) reached" in terminal_state["feedback"]

        # Check recorded sequence: eval0 -> rev1 -> eval1 -> rev2 -> eval2 -> limit_reached
        events = [e.event_type for e in logger.get_events("run-always-revise")]
        assert events == [
            EventType.EVALUATION_COMPLETED,  # rev 0 eval -> revise
            EventType.REVISION_REQUESTED,
            EventType.REVISION_COMPLETED,   # rev 1 done
            EventType.EVALUATION_COMPLETED,  # rev 1 eval -> revise
            EventType.REVISION_REQUESTED,
            EventType.REVISION_COMPLETED,   # rev 2 done
            EventType.EVALUATION_COMPLETED,  # rev 2 eval -> revise (limit reached)
            EventType.REVISION_LIMIT_REACHED,
        ]

        # Evaluator called exactly 3 times
        assert len(evaluator.call_history) == 3
