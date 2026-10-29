"""CLI interface for Task 4 — Resumable Review Workflow.

Provides commands:
  run     - Start a new review workflow for a content item
  resume  - Inspect the saved checkpoint of a paused workflow
  approve - Resume and approve a paused workflow to reach completion
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Optional

from workflow.evaluator import DeterministicEvaluator
from workflow.events import EventLogger
from workflow.graph import create_review_workflow
from workflow.models import (
    ContentItem,
    EventType,
    WorkflowState,
    WorkflowStatus,
    validate_workflow_input,
)
from workflow.persistence import get_sqlite_checkpointer


def get_default_paths() -> tuple[Path, Path, Path]:
    """Return default paths for DB, log file, and fixtures directory."""
    pkg_dir = Path(__file__).resolve().parent.parent
    db_path = pkg_dir / "workflow_state.db"
    log_file = pkg_dir / "events.jsonl"
    fixtures_dir = pkg_dir / "fixtures"
    return db_path, log_file, fixtures_dir


def load_content_fixture(content_id: str, fixtures_dir: Path) -> ContentItem:
    """Load mock content fixture by ID."""
    content_file = fixtures_dir / "content.json"
    if not content_file.exists():
        raise FileNotFoundError(f"Content fixtures file not found: {content_file}")

    with open(content_file, "r", encoding="utf-8") as f:
        items = json.load(f)

    if content_id not in items:
        # Fallback to create a synthetic content item if not found in fixtures
        return ContentItem(
            content_id=content_id,
            title=f"Draft Document ({content_id})",
            body=f"Draft body content for item {content_id}.",
            metadata={"source": "cli_default"},
        )

    return ContentItem.model_validate(items[content_id])


def run_command(
    content_id: str,
    scenario: str = "one_revision_then_pass",
    db_path: Optional[Path] = None,
    log_file: Optional[Path] = None,
    fixtures_dir: Optional[Path] = None,
) -> int:
    """Start and run a workflow until pause or completion."""
    default_db, default_log, default_fix = get_default_paths()
    db = db_path or default_db
    log = log_file or default_log
    fix = fixtures_dir or default_fix

    print(f"\n--- Starting Workflow for '{content_id}' (Scenario: {scenario}) ---")

    # Load and validate content input
    try:
        content_item = load_content_fixture(content_id, fix)
        raw_input = {
            "run_id": f"run_{content_id}",
            "content_id": content_id,
            "content": content_item.model_dump(),
        }
        initial_state = validate_workflow_input(raw_input)
    except Exception as exc:
        print(f"Validation Failure: {exc}", file=sys.stderr)
        return 1

    saver = get_sqlite_checkpointer(db)
    logger = EventLogger(log_file=log)
    evaluator = DeterministicEvaluator(scenario_name=scenario, fixtures_path=fix / "evaluator_scenarios.json")
    graph = create_review_workflow(evaluator=evaluator, event_logger=logger, checkpointer=saver)

    config = {"configurable": {"thread_id": content_id}}

    # Record workflow start
    logger.record_event(
        run_id=initial_state.run_id,
        content_id=content_id,
        event_type=EventType.WORKFLOW_STARTED,
        stage="init",
        payload={"scenario": scenario},
    )

    result = graph.invoke(initial_state, config=config)
    saver.conn.close()

    status = result.get("status")
    print(f"\nEvaluation completed")
    print(f"Decision: {result.get('evaluation_result')}")
    print(f"Revision count: {result.get('revision_count')}")

    if status == WorkflowStatus.HUMAN_REVIEW:
        print("\nHuman review required")
        print(f"Checkpoint saved to {db.name}")
        print("Workflow paused.")
        print(f"Run 'python -m workflow.cli resume {content_id}' to inspect checkpoint.")
        print(f"Run 'python -m workflow.cli approve {content_id}' to approve and complete.\n")
        return 0
    elif status == WorkflowStatus.REVISION_LIMIT_REACHED:
        print(f"\nMaximum revision attempts reached: {result.get('feedback')}")
        print("Workflow stopped.\n")
        return 0
    elif status == WorkflowStatus.COMPLETED:
        print("\nWorkflow completed immediately.\n")
        return 0

    return 0


def resume_command(
    content_id: str,
    db_path: Optional[Path] = None,
    log_file: Optional[Path] = None,
) -> int:
    """Inspect the saved checkpoint state without advancing the workflow."""
    default_db, default_log, _ = get_default_paths()
    db = db_path or default_db
    log = log_file or default_log

    if not db.exists():
        print(f"Error: Database {db} does not exist. Run the workflow first.", file=sys.stderr)
        return 1

    saver = get_sqlite_checkpointer(db)
    logger = EventLogger(log_file=log)
    graph = create_review_workflow(event_logger=logger, checkpointer=saver)

    config = {"configurable": {"thread_id": content_id}}
    state_snapshot = graph.get_state(config)
    saver.conn.close()

    if not state_snapshot.values:
        print(f"No checkpoint found for thread '{content_id}'.", file=sys.stderr)
        return 1

    values = state_snapshot.values
    print(f"\n--- Loaded Checkpoint for '{content_id}' ---")
    print(f"Current stage: {values.get('status')}")
    print(f"Revision count: {values.get('revision_count')}")
    print(f"Evaluation result: {values.get('evaluation_result')}")
    print(f"Checkpoint version: {values.get('checkpoint_version')}")
    print(f"Pending next nodes: {state_snapshot.next}")

    if values.get("status") == WorkflowStatus.HUMAN_REVIEW:
        print("\nApproval required.")
        print(f"Run 'python -m workflow.cli approve {content_id}' to proceed.\n")
    elif values.get("status") == WorkflowStatus.COMPLETED:
        print("\nWorkflow is already completed.\n")
    return 0


def approve_command(
    content_id: str,
    db_path: Optional[Path] = None,
    log_file: Optional[Path] = None,
) -> int:
    """Resume execution from the saved checkpoint and apply approval."""
    default_db, default_log, _ = get_default_paths()
    db = db_path or default_db
    log = log_file or default_log

    if not db.exists():
        print(f"Error: Database {db} does not exist. Run the workflow first.", file=sys.stderr)
        return 1

    saver = get_sqlite_checkpointer(db)
    logger = EventLogger(log_file=log)
    graph = create_review_workflow(event_logger=logger, checkpointer=saver)

    config = {"configurable": {"thread_id": content_id}}
    state_snapshot = graph.get_state(config)

    if not state_snapshot.values:
        saver.conn.close()
        print(f"No checkpoint found for '{content_id}'.", file=sys.stderr)
        return 1

    current_status = state_snapshot.values.get("status")

    if current_status == WorkflowStatus.COMPLETED:
        print("\nApproval attempted on already-completed workflow.")
        # Trigger idempotent complete node check
        state_obj = WorkflowState.model_validate(state_snapshot.values)
        from workflow.graph import complete_node
        complete_node(state_obj, logger)
        saver.conn.close()
        print("Duplicate approval ignored. No changes made.\n")
        return 0

    print(f"\nLoaded checkpoint for '{content_id}'")
    print(f"Current stage: {current_status}")
    print("Approval required.")
    print("Approved.")

    # Resume the graph from saved checkpoint
    resumed = graph.invoke(None, config=config)
    saver.conn.close()

    print(f"\nFinal status: {resumed.get('status')}")
    print("Workflow completed.\n")
    return 0


def main(args: Optional[list[str]] = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="workflow_cli",
        description="Task 4 — Resumable Review Workflow CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Start review workflow")
    run_parser.add_argument("content_id", help="Content item ID (e.g. content-001)")
    run_parser.add_argument(
        "--scenario",
        default="one_revision_then_pass",
        choices=["normal_pass", "one_revision_then_pass", "always_revise"],
        help="Deterministic evaluator scenario to execute",
    )
    run_parser.add_argument("--db-path", type=Path, default=None, help="SQLite checkpoint DB path")
    run_parser.add_argument("--log-file", type=Path, default=None, help="JSONL event log path")

    # Subcommand: resume
    resume_parser = subparsers.add_parser("resume", help="Inspect saved workflow checkpoint")
    resume_parser.add_argument("content_id", help="Content item ID to inspect")
    resume_parser.add_argument("--db-path", type=Path, default=None, help="SQLite checkpoint DB path")
    resume_parser.add_argument("--log-file", type=Path, default=None, help="JSONL event log path")

    # Subcommand: approve
    approve_parser = subparsers.add_parser("approve", help="Resume and approve paused workflow")
    approve_parser.add_argument("content_id", help="Content item ID to approve")
    approve_parser.add_argument("--db-path", type=Path, default=None, help="SQLite checkpoint DB path")
    approve_parser.add_argument("--log-file", type=Path, default=None, help="JSONL event log path")

    parsed = parser.parse_args(args)

    if parsed.command == "run":
        return run_command(
            content_id=parsed.content_id,
            scenario=parsed.scenario,
            db_path=parsed.db_path,
            log_file=parsed.log_file,
        )
    elif parsed.command == "resume":
        return resume_command(
            content_id=parsed.content_id,
            db_path=parsed.db_path,
            log_file=parsed.log_file,
        )
    elif parsed.command == "approve":
        return approve_command(
            content_id=parsed.content_id,
            db_path=parsed.db_path,
            log_file=parsed.log_file,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
