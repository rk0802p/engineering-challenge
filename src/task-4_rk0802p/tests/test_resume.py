"""Test checkpoint persistence and process resumption (Task 4 Phase 3 & Phase 5).

Verifies:
- Checkpoints are saved to SQLite at the human-review boundary.
- A new Python process loads the persisted state via thread_id without losing data.
- Resumption does NOT rerun previously completed evaluation or revision nodes.
- Repeated approval on completed workflows is idempotent and emits no duplicate events.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from workflow.evaluator import DeterministicEvaluator
from workflow.events import EventLogger
from workflow.graph import create_review_workflow
from workflow.models import (
    ContentItem,
    EvaluationDecision,
    EventType,
    WorkflowState,
    WorkflowStatus,
)
from workflow.persistence import get_sqlite_checkpointer


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def sample_content() -> ContentItem:
    return ContentItem(
        content_id="content-001",
        title="Quarterly Technical Report Q3",
        body="Initial report body detailing architectural performance metrics.",
        metadata={"category": "technical_report"},
    )


class TestSQLitePersistenceAndResume:
    """Verify SQLite persistence across simulated and real process restarts."""

    def test_checkpoint_persists_to_sqlite_and_resumes_without_rerunning_work(
        self, sample_content, fixtures_dir
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflow_state.db"
            log_path = Path(tmpdir) / "events.jsonl"
            thread_id = "thread-content-001"
            config = {"configurable": {"thread_id": thread_id}}

            # Session 1: Run with one_revision_then_pass until human review pause
            evaluator1 = DeterministicEvaluator(
                scenario_name="one_revision_then_pass",
                fixtures_path=fixtures_dir / "evaluator_scenarios.json",
            )
            logger1 = EventLogger(log_file=log_path)
            saver1 = get_sqlite_checkpointer(db_path)
            graph1 = create_review_workflow(
                evaluator=evaluator1, event_logger=logger1, checkpointer=saver1
            )

            initial_state = WorkflowState(
                run_id="run-session-1",
                content_id=sample_content.content_id,
                content=sample_content,
            )

            paused = graph1.invoke(initial_state, config=config)
            assert paused["status"] == WorkflowStatus.HUMAN_REVIEW
            assert paused["revision_count"] == 1
            assert len(evaluator1.call_history) == 2  # 1st: revise, 2nd: human_review
            saver1.conn.close()

            # Session 2: Fresh checkpointer connection, new evaluator instance with empty history
            saver2 = get_sqlite_checkpointer(db_path)
            evaluator2 = DeterministicEvaluator(
                scenario_name="one_revision_then_pass",
                fixtures_path=fixtures_dir / "evaluator_scenarios.json",
            )
            logger2 = EventLogger(log_file=log_path)
            graph2 = create_review_workflow(
                evaluator=evaluator2, event_logger=logger2, checkpointer=saver2
            )

            # Inspect state loaded from SQLite before resuming
            saved_checkpoint = graph2.get_state(config)
            assert saved_checkpoint.values["status"] == WorkflowStatus.HUMAN_REVIEW
            assert saved_checkpoint.values["revision_count"] == 1
            assert saved_checkpoint.values["content_id"] == "content-001"
            assert saved_checkpoint.next == ("complete",)

            # Resume execution
            resumed = graph2.invoke(None, config=config)
            assert resumed["status"] == WorkflowStatus.COMPLETED

            # CRITICAL CHECK: Evaluator in session 2 was NEVER called!
            assert len(evaluator2.call_history) == 0, (
                "Work was unnecessarily rerun! Evaluator should not be called on resume."
            )

            # Inspect event log: evaluation and revision are only logged once
            events = logger2.get_events("run-session-1")
            eval_events = [e for e in events if e.event_type == EventType.EVALUATION_COMPLETED]
            rev_events = [e for e in events if e.event_type == EventType.REVISION_COMPLETED]
            comp_events = [e for e in events if e.event_type == EventType.WORKFLOW_COMPLETED]

            assert len(eval_events) == 2  # Exactly 2 evaluations occurred in Session 1
            assert len(rev_events) == 1   # Exactly 1 revision occurred in Session 1
            assert len(comp_events) == 1  # Exactly 1 completion occurred on resume
            saver2.conn.close()

    def test_subprocess_restart_resumption(self, sample_content, fixtures_dir):
        """Simulate a full OS process termination and restart using subprocess."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "subproc_checkpoint.db"
            log_path = Path(tmpdir) / "subproc_events.jsonl"
            thread_id = "thread-subproc-001"
            root_dir = Path(__file__).resolve().parent.parent

            # Subprocess 1: Start workflow and pause at review boundary
            code_proc1 = f"""
import sys
sys.path.insert(0, {json.dumps(str(root_dir))})
from pathlib import Path
from workflow.models import ContentItem, WorkflowState
from workflow.evaluator import DeterministicEvaluator
from workflow.events import EventLogger
from workflow.graph import create_review_workflow
from workflow.persistence import get_sqlite_checkpointer

saver = get_sqlite_checkpointer(Path({json.dumps(str(db_path))}))
logger = EventLogger(log_file=Path({json.dumps(str(log_path))}))
evaluator = DeterministicEvaluator(scenario_name='normal_pass')
graph = create_review_workflow(evaluator=evaluator, event_logger=logger, checkpointer=saver)

content = ContentItem(content_id='content-001', title='Title', body='Body')
state = WorkflowState(run_id='run-subproc', content_id='content-001', content=content)
config = {{'configurable': {{'thread_id': {json.dumps(thread_id)}}}}}

res = graph.invoke(state, config=config)
saver.conn.close()
assert res['status'] == 'human_review'
"""
            run1 = subprocess.run(
                [sys.executable, "-c", code_proc1],
                capture_output=True,
                text=True,
            )
            assert run1.returncode == 0, f"Process 1 failed: {run1.stderr}"

            # Subprocess 2: Separate brand-new OS process resumes checkpoint
            code_proc2 = f"""
import sys
sys.path.insert(0, {json.dumps(str(root_dir))})
from pathlib import Path
from workflow.evaluator import DeterministicEvaluator
from workflow.events import EventLogger
from workflow.graph import create_review_workflow
from workflow.persistence import get_sqlite_checkpointer

saver = get_sqlite_checkpointer(Path({json.dumps(str(db_path))}))
logger = EventLogger(log_file=Path({json.dumps(str(log_path))}))
# Evaluator here would fail if called
evaluator = DeterministicEvaluator(responses=[])
graph = create_review_workflow(evaluator=evaluator, event_logger=logger, checkpointer=saver)
config = {{'configurable': {{'thread_id': {json.dumps(thread_id)}}}}}

# Check state loaded
state = graph.get_state(config)
assert state.values['status'] == 'human_review'

# Resume
res = graph.invoke(None, config=config)
saver.conn.close()
assert res['status'] == 'completed'
assert len(evaluator.call_history) == 0
"""
            run2 = subprocess.run(
                [sys.executable, "-c", code_proc2],
                capture_output=True,
                text=True,
            )
            assert run2.returncode == 0, f"Process 2 failed: {run2.stderr}"


class TestDuplicateApprovalIdempotency:
    """Verify that approving an already-completed workflow does not repeat side effects."""

    def test_duplicate_approval_does_not_repeat_completion(self, sample_content, fixtures_dir):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "idempotent.db"
            log_path = Path(tmpdir) / "idempotent_events.jsonl"
            thread_id = "thread-idempotent"
            config = {"configurable": {"thread_id": thread_id}}

            saver = get_sqlite_checkpointer(db_path)
            logger = EventLogger(log_file=log_path)
            evaluator = DeterministicEvaluator(scenario_name="normal_pass")
            graph = create_review_workflow(
                evaluator=evaluator, event_logger=logger, checkpointer=saver
            )

            state = WorkflowState(
                run_id="run-idem",
                content_id=sample_content.content_id,
                content=sample_content,
            )

            # 1. Reach pause
            graph.invoke(state, config=config)

            # 2. First approval: completes
            res1 = graph.invoke(None, config=config)
            assert res1["status"] == WorkflowStatus.COMPLETED

            events_after_first = list(logger.get_events("run-idem"))
            completed_events = [e for e in events_after_first if e.event_type == EventType.WORKFLOW_COMPLETED]
            assert len(completed_events) == 1

            # 3. Second approval attempt: idempotent safeguard
            from workflow.graph import complete_node
            state_completed = WorkflowState.model_validate(res1)
            second_result = complete_node(state_completed, logger)
            assert second_result == {}  # No state change

            events_after_second = logger.get_events("run-idem")
            completed_events_after = [
                e for e in events_after_second if e.event_type == EventType.WORKFLOW_COMPLETED
            ]
            duplicate_events = [
                e for e in events_after_second if e.event_type == EventType.DUPLICATE_APPROVAL_IGNORED
            ]

            assert len(completed_events_after) == 1, "Duplicate completion event was logged!"
            assert len(duplicate_events) == 1, "Expected DUPLICATE_APPROVAL_IGNORED event."

            saver.conn.close()

    def test_cli_duplicate_approval_across_separate_processes(self, fixtures_dir):
        """Verify CLI duplicate approval remains idempotent when executed across new OS processes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "cli_idempotent.db"
            log_path = Path(tmpdir) / "cli_events.jsonl"
            content_id = "content-001"
            root_dir = Path(__file__).resolve().parent.parent

            # Process 1: run command
            proc1 = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "workflow.cli",
                    "run",
                    content_id,
                    "--scenario",
                    "normal_pass",
                    "--db-path",
                    str(db_path),
                    "--log-file",
                    str(log_path),
                ],
                cwd=root_dir,
                capture_output=True,
                text=True,
            )
            assert proc1.returncode == 0, f"CLI run failed: {proc1.stderr}"
            assert "Workflow paused." in proc1.stdout

            # Process 2: first approve command
            proc2 = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "workflow.cli",
                    "approve",
                    content_id,
                    "--db-path",
                    str(db_path),
                    "--log-file",
                    str(log_path),
                ],
                cwd=root_dir,
                capture_output=True,
                text=True,
            )
            assert proc2.returncode == 0, f"CLI approve 1 failed: {proc2.stderr}"
            assert "Workflow completed." in proc2.stdout

            # Process 3: second approve command in a completely new OS process
            proc3 = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "workflow.cli",
                    "approve",
                    content_id,
                    "--db-path",
                    str(db_path),
                    "--log-file",
                    str(log_path),
                ],
                cwd=root_dir,
                capture_output=True,
                text=True,
            )
            assert proc3.returncode == 0, f"CLI approve 2 failed: {proc3.stderr}"
            assert "Duplicate approval ignored." in proc3.stdout

            # Verify event log only has 1 completion event
            logger = EventLogger(log_file=log_path)
            events = logger.get_events(f"run_{content_id}")
            completed_events = [e for e in events if e.event_type == EventType.WORKFLOW_COMPLETED]
            duplicate_events = [e for e in events if e.event_type == EventType.DUPLICATE_APPROVAL_IGNORED]
            assert len(completed_events) == 1
            assert len(duplicate_events) == 1

    def test_interruption_before_checkpoint_does_not_duplicate_audit_events(self):
        """Verify that an interrupted step before checkpointing does not record duplicate events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "idempotent_event_log.jsonl"
            logger = EventLogger(log_file=log_path)

            # Record event once
            logger.record_event(
                run_id="run-interrupt-test",
                content_id="content-001",
                event_type=EventType.HUMAN_REVIEW_REQUIRED,
                stage="human_review",
                revision_count=1,
                payload={"attempt": 1},
            )
            # Re-attempt event recording (simulating node rerun after interruption)
            logger.record_event(
                run_id="run-interrupt-test",
                content_id="content-001",
                event_type=EventType.HUMAN_REVIEW_REQUIRED,
                stage="human_review",
                revision_count=1,
                payload={"attempt": 2},
            )

            # Reload from disk to verify disk file has exactly 1 event
            logger2 = EventLogger(log_file=log_path)
            events = logger2.get_events("run-interrupt-test")
            assert len(events) == 1
