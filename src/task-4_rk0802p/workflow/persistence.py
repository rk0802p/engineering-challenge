"""Persistence and checkpoint configuration for Task 4.

Provides factory functions to configure SQLite-backed or in-memory checkpointers
with proper serde allowlists for custom Pydantic models.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver, JsonPlusSerializer
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

ALLOWED_MODULES = [
    ("workflow.models", "ContentItem"),
    ("workflow.models", "WorkflowStatus"),
    ("workflow.models", "EvaluationDecision"),
    ("workflow.models", "WorkflowState"),
    ("workflow.models", "EvaluatorResponse"),
    ("workflow.models", "WorkflowEvent"),
]


def get_default_serde() -> JsonPlusSerializer:
    """Return JsonPlusSerializer configured with allowed custom model types."""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MODULES)


def get_memory_checkpointer() -> MemorySaver:
    """Create an in-memory checkpointer configured with allowed custom model types."""
    return MemorySaver(serde=get_default_serde())


def get_sqlite_checkpointer(db_path: Path | str) -> SqliteSaver:
    """Create a persistent SQLite-backed checkpointer.

    Args:
        db_path: Path to local SQLite database file.

    Returns:
        Configured SqliteSaver with schemas initialized.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn, serde=get_default_serde())
    saver.setup()
    return saver
