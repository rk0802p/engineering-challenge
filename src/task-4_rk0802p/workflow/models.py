"""Typed workflow contracts and Pydantic models for Task 4.

Defines schemas for:
- Content items
- Evaluator decisions and responses
- Workflow state
- Audit event logs
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationDecision(str, Enum):
    """Supported decisions from the automated evaluator."""
    REVISE = "revise"
    HUMAN_REVIEW = "human_review"


class WorkflowStatus(str, Enum):
    """Lifecycle statuses for the review workflow."""
    PENDING = "pending"
    EVALUATING = "evaluating"
    REVISING = "revising"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    REVISION_LIMIT_REACHED = "revision_limit_reached"
    COMPLETED = "completed"


class EventType(str, Enum):
    """Event types for inspectable audit log."""
    WORKFLOW_STARTED = "workflow_started"
    EVALUATION_COMPLETED = "evaluation_completed"
    REVISION_REQUESTED = "revision_requested"
    REVISION_COMPLETED = "revision_completed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    CHECKPOINT_SAVED = "checkpoint_saved"
    HUMAN_APPROVED = "human_approved"
    REVISION_LIMIT_REACHED = "revision_limit_reached"
    WORKFLOW_COMPLETED = "workflow_completed"
    DUPLICATE_APPROVAL_IGNORED = "duplicate_approval_ignored"


class ContentItem(BaseModel):
    """Input content item subjected to automated evaluation and review."""
    model_config = ConfigDict(extra="forbid")

    content_id: str = Field(..., description="Unique identifier for the content item")
    title: str = Field(..., description="Content title / headline")
    body: str = Field(..., description="Draft content body")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")

    @field_validator("content_id", "title", "body")
    @classmethod
    def check_non_empty_str(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(f"Field '{info.field_name}' must not be empty or whitespace only.")
        return value.strip()


class EvaluatorResponse(BaseModel):
    """Deterministic output produced by the content evaluator."""
    model_config = ConfigDict(extra="forbid")

    decision: EvaluationDecision = Field(..., description="Routing decision: revise or human_review")
    feedback: str = Field(default="", description="Detailed feedback or justification")
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Normalized quality score [0.0, 1.0]")
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when evaluation was executed"
    )

    @field_validator("decision", mode="before")
    @classmethod
    def validate_decision_enum(cls, value: Any) -> EvaluationDecision:
        if isinstance(value, EvaluationDecision):
            return value
        if isinstance(value, str):
            try:
                return EvaluationDecision(value.lower().strip())
            except ValueError:
                valid_options = [d.value for d in EvaluationDecision]
                raise ValueError(
                    f"Unknown evaluator decision '{value}'. Expected one of: {valid_options}"
                )
        raise ValueError(f"Invalid decision type: {type(value)}. Must be string or EvaluationDecision.")


class WorkflowEvent(BaseModel):
    """Immutable audit event recorded along workflow execution."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(
        default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}",
        description="Unique event ID for deduplication and audit trail"
    )
    run_id: str = Field(..., min_length=1, description="Execution run identifier")
    content_id: str = Field(..., min_length=1, description="Associated content identifier")
    event_type: EventType = Field(..., description="Categorical event type")
    stage: str = Field(..., min_length=1, description="Current workflow stage")
    revision_count: int = Field(default=0, ge=0, description="Number of revisions completed so far")
    payload: dict[str, Any] = Field(default_factory=dict, description="Stage-specific contextual payload")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the event"
    )

    @field_validator("event_type", mode="before")
    @classmethod
    def validate_event_type(cls, value: Any) -> EventType:
        if isinstance(value, EventType):
            return value
        if isinstance(value, str):
            try:
                return EventType(value.lower().strip())
            except ValueError:
                valid_options = [e.value for e in EventType]
                raise ValueError(
                    f"Unknown event type '{value}'. Expected one of: {valid_options}"
                )
        raise ValueError(f"Invalid event_type type: {type(value)}")


class WorkflowState(BaseModel):
    """Complete typed state of the review workflow graph."""
    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(..., min_length=1, description="Unique workflow run ID")
    content_id: str = Field(..., min_length=1, description="Content item ID")
    content: ContentItem = Field(..., description="Current draft of the content item")
    status: WorkflowStatus = Field(
        default=WorkflowStatus.PENDING,
        description="Current workflow lifecycle status"
    )
    revision_count: int = Field(
        default=0, ge=0,
        description="Number of revisions attempted so far"
    )
    max_revisions: int = Field(
        default=2, ge=1,
        description="Configurable ceiling on revision attempts before terminal stop"
    )
    evaluation_result: Optional[EvaluationDecision] = Field(
        default=None,
        description="Last decision returned by the automated evaluator"
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Feedback from the most recent evaluation or revision"
    )
    checkpoint_version: int = Field(
        default=0, ge=0,
        description="Monotonically incrementing checkpoint sequence number"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Workflow initiation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last state modification timestamp"
    )


def validate_workflow_input(input_data: dict[str, Any] | Any) -> WorkflowState:
    """Validate raw input before starting workflow execution.

    Ensures that content item and initial state conform to schema contracts.
    Raises pydantic.ValidationError if invalid.
    """
    if isinstance(input_data, WorkflowState):
        return input_data
    if not isinstance(input_data, dict):
        raise TypeError(f"Workflow input must be a dictionary or WorkflowState, got {type(input_data)}")

    return WorkflowState.model_validate(input_data)
