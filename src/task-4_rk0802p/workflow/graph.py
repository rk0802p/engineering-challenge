"""LangGraph workflow definition for Task 4 — Resumable Review Workflow.

Defines explicit nodes and conditional routing for:
- Automated evaluation
- Bounded revision loop (<= 2 attempts)
- Human review pause boundary (with checkpointing)
- Approval and idempotent completion
- Terminal state on revision limit
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from workflow.evaluator import DeterministicEvaluator
from workflow.events import EventLogger
from workflow.models import (
    EvaluationDecision,
    EventType,
    WorkflowState,
    WorkflowStatus,
)
from workflow.persistence import get_memory_checkpointer


def evaluate_node(
    state: WorkflowState,
    evaluator: DeterministicEvaluator,
    event_logger: EventLogger,
) -> dict[str, Any]:
    """Execute automated content evaluation."""
    response = evaluator.evaluate(state.content, state.revision_count)

    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.EVALUATION_COMPLETED,
        stage="evaluation",
        revision_count=state.revision_count,
        payload={
            "decision": response.decision.value,
            "feedback": response.feedback,
            "score": response.score,
        },
    )

    return {
        "evaluation_result": response.decision,
        "feedback": response.feedback,
        "status": WorkflowStatus.EVALUATING,
        "updated_at": datetime.now(timezone.utc),
    }


def route_after_evaluation(state: WorkflowState) -> str:
    """Conditionally route graph based on evaluator response and revision count."""
    if state.evaluation_result == EvaluationDecision.REVISE:
        if state.revision_count >= state.max_revisions:
            return "revision_limit_reached"
        return "revise"
    elif state.evaluation_result == EvaluationDecision.HUMAN_REVIEW:
        return "human_review"
    else:
        raise ValueError(f"Unknown evaluator decision: '{state.evaluation_result}'")


def revise_node(
    state: WorkflowState,
    event_logger: EventLogger,
) -> dict[str, Any]:
    """Increment revision count, apply revision updates, and route back to evaluate."""
    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.REVISION_REQUESTED,
        stage="revision",
        revision_count=state.revision_count,
        payload={"reason": state.feedback or "Automated evaluator requested revision."},
    )

    next_revision_count = state.revision_count + 1
    updated_body = f"{state.content.body}\n[Revision {next_revision_count}: feedback '{state.feedback}']"
    revised_content = state.content.model_copy(update={"body": updated_body})

    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.REVISION_COMPLETED,
        stage="revision",
        revision_count=next_revision_count,
        payload={"updated_body": updated_body},
    )

    return {
        "revision_count": next_revision_count,
        "content": revised_content,
        "status": WorkflowStatus.REVISING,
        "updated_at": datetime.now(timezone.utc),
    }


def human_review_node(
    state: WorkflowState,
    event_logger: EventLogger,
) -> dict[str, Any]:
    """Human review pause boundary. Persists state checkpoint and stops."""
    next_checkpoint = state.checkpoint_version + 1

    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.HUMAN_REVIEW_REQUIRED,
        stage="human_review",
        revision_count=state.revision_count,
        payload={"checkpoint_version": next_checkpoint},
    )

    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.CHECKPOINT_SAVED,
        stage="human_review",
        revision_count=state.revision_count,
        payload={"stage": "human_review", "checkpoint_version": next_checkpoint},
    )

    return {
        "status": WorkflowStatus.HUMAN_REVIEW,
        "checkpoint_version": next_checkpoint,
        "updated_at": datetime.now(timezone.utc),
    }


def complete_node(
    state: WorkflowState,
    event_logger: EventLogger,
) -> dict[str, Any]:
    """Complete the review workflow upon human approval, enforcing idempotency."""
    # Safeguard against duplicate approvals
    if (
        state.status == WorkflowStatus.COMPLETED
        or event_logger.has_event(state.run_id, EventType.WORKFLOW_COMPLETED)
    ):
        event_logger.record_event(
            run_id=state.run_id,
            content_id=state.content_id,
            event_type=EventType.DUPLICATE_APPROVAL_IGNORED,
            stage="completion",
            revision_count=state.revision_count,
            payload={"reason": "Workflow already completed. Redundant approval ignored."},
        )
        return {}

    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.HUMAN_APPROVED,
        stage="human_review",
        revision_count=state.revision_count,
        payload={"decision": "approved"},
    )

    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.WORKFLOW_COMPLETED,
        stage="completion",
        revision_count=state.revision_count,
        payload={"final_status": "completed"},
    )

    return {
        "status": WorkflowStatus.COMPLETED,
        "updated_at": datetime.now(timezone.utc),
    }


def revision_limit_reached_node(
    state: WorkflowState,
    event_logger: EventLogger,
) -> dict[str, Any]:
    """Terminal node reached when retry/revision ceiling is exceeded."""
    reason = f"Maximum revision attempts ({state.max_revisions}) reached."

    event_logger.record_event(
        run_id=state.run_id,
        content_id=state.content_id,
        event_type=EventType.REVISION_LIMIT_REACHED,
        stage="terminal",
        revision_count=state.revision_count,
        payload={
            "max_revisions": state.max_revisions,
            "reason": reason,
        },
    )

    return {
        "status": WorkflowStatus.REVISION_LIMIT_REACHED,
        "feedback": reason,
        "updated_at": datetime.now(timezone.utc),
    }


def create_review_workflow(
    evaluator: Optional[DeterministicEvaluator] = None,
    event_logger: Optional[EventLogger] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
    use_default_memory_checkpointer: bool = True,
) -> CompiledStateGraph:
    """Build and compile the LangGraph review workflow.

    Args:
        evaluator: DeterministicEvaluator instance.
        event_logger: EventLogger instance.
        checkpointer: Checkpointer (e.g. SqliteSaver or MemorySaver).
        use_default_memory_checkpointer: If True and checkpointer is None, uses MemorySaver.

    Returns:
        CompiledStateGraph paused after 'human_review'.
    """
    ev = evaluator if evaluator is not None else DeterministicEvaluator()
    logger = event_logger if event_logger is not None else EventLogger()

    if checkpointer is None and use_default_memory_checkpointer:
        checkpointer = get_memory_checkpointer()

    builder = StateGraph(WorkflowState)

    # Bind nodes with dependencies
    builder.add_node("evaluate", lambda state: evaluate_node(state, ev, logger))
    builder.add_node("revise", lambda state: revise_node(state, logger))
    builder.add_node("human_review", lambda state: human_review_node(state, logger))
    builder.add_node("complete", lambda state: complete_node(state, logger))
    builder.add_node("revision_limit_reached", lambda state: revision_limit_reached_node(state, logger))

    # Define edges and routing
    builder.add_edge(START, "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        route_after_evaluation,
        {
            "revise": "revise",
            "human_review": "human_review",
            "revision_limit_reached": "revision_limit_reached",
        },
    )
    builder.add_edge("revise", "evaluate")
    builder.add_edge("human_review", "complete")
    builder.add_edge("complete", END)
    builder.add_edge("revision_limit_reached", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_after=["human_review"],
    )
