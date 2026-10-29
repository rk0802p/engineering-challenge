"""Event logging and audit trail for Task 4 review workflow.

Maintains an inspectable record of state transitions, supporting in-memory
collection and JSON Lines (.jsonl) persistence with idempotency safeguards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from workflow.models import EventType, WorkflowEvent


class EventLogger:
    """Audit event logger supporting in-memory tracking and .jsonl file export."""

    def __init__(self, log_file: Optional[Path | str] = None) -> None:
        self.log_file = Path(log_file) if log_file else None
        self._events: List[WorkflowEvent] = []
        if self.log_file and self.log_file.exists():
            self._load_existing_log()

    def _load_existing_log(self) -> None:
        """Load past events from existing log file if present."""
        if not self.log_file or not self.log_file.exists():
            return
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        self._events.append(WorkflowEvent.model_validate(data))
                    except Exception:
                        continue

    def record_event(
        self,
        run_id: str,
        content_id: str,
        event_type: EventType | str,
        stage: str,
        revision_count: int = 0,
        payload: Optional[dict[str, Any]] = None,
        event_id: Optional[str] = None,
    ) -> WorkflowEvent:
        """Record a structured workflow event and persist to log file if configured."""
        kwargs: dict[str, Any] = {
            "run_id": run_id,
            "content_id": content_id,
            "event_type": event_type,
            "stage": stage,
            "revision_count": revision_count,
            "payload": payload or {},
        }
        if event_id:
            kwargs["event_id"] = event_id

        event = WorkflowEvent(**kwargs)
        self._events.append(event)

        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")

        return event

    def has_event(self, run_id: str, event_type: EventType | str, stage: Optional[str] = None) -> bool:
        """Check if an event matching criteria has already been recorded."""
        et = EventType(event_type) if isinstance(event_type, str) else event_type
        for e in self._events:
            if e.run_id == run_id and e.event_type == et:
                if stage is None or e.stage == stage:
                    return True
        return False

    def get_events(self, run_id: Optional[str] = None) -> List[WorkflowEvent]:
        """Return all recorded events, optionally filtered by run_id."""
        if run_id is None:
            return list(self._events)
        return [e for e in self._events if e.run_id == run_id]

    def clear(self) -> None:
        """Clear in-memory events."""
        self._events.clear()
