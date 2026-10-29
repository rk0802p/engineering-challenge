# Task 4 — Resumable Review Workflow

**Candidate:** rk0802p  
**Task:** Task 4 — Resumable Review Workflow  
**Framework:** Python 3.11+ / LangGraph / Pydantic v2 / SQLite checkpointing  

---

## 1. Overview & Objective

This project implements a resumable content review and approval workflow orchestrated by **LangGraph**. The workflow coordinates automated content evaluation, bounded revisions (up to 2 attempts), and human-in-the-loop review.

### Key Capabilities
- **Resumable Execution**: Pauses at the human-review boundary, persisting graph state in SQLite so the process can restart and resume without rerunning completed evaluation or revision work.
- **Bounded Revisions**: Enforces a strict limit of at most two revision attempts to prevent infinite evaluation-revision loops.
- **Strict Typed Contracts**: Validates all content items, evaluator responses, events, and graph states using Pydantic models before execution.
- **Idempotent Approvals**: Guarantees that duplicate human approvals on completed workflows are safely ignored without duplicating completion events or downstream side effects.
- **Deterministic Evaluation**: Supports fixture-driven deterministic responses without requiring external API keys or network dependencies.
- **Inspectable Event Log**: Records structured JSON Lines audit events (`.jsonl`) tracking each transition.

---

## 2. Architecture & Design

### Workflow Routing Graph

```text
       [ Start ]
           │
           ▼
     [ Evaluate ] ◄────────┐
           │               │
     { Decision }          │
      ├── revise (count < 2)
      │    │
      │    ▼
      │ [ Revise ] ────────┘
      │
      ├── revise (count >= 2) ──► [ Revision Limit Reached ] (Terminal)
      │
      └── human_review
           │
           ▼
     [ Human Review ] (Checkpoint saved & Process pauses)
           │
     (Process Resume & Approve)
           │
           ▼
      [ Complete ] (Terminal)
```

### Typed Workflow Contracts
- `ContentItem`: Validates draft content (`content_id`, `title`, `body`, `metadata`). Rejects empty or whitespace-only inputs and forbids unauthorized fields.
- `EvaluatorResponse`: Enforces deterministic decisions (`revise` or `human_review`), optional normalized quality score `[0.0, 1.0]`, and feedback notes. Any unknown decision fails validation immediately.
- `WorkflowState`: Preserves workflow execution state (`run_id`, `content_id`, `content`, `status`, `revision_count`, `max_revisions`, `evaluation_result`, `checkpoint_version`).
- `WorkflowEvent`: Structured audit event record with unique event ID, timestamp, stage, and payload for deterministic event log reconstruction.

### Persistence & Checkpointing Strategy
- Checkpoints are persisted in SQLite using `SqliteSaver` from `langgraph-checkpoint-sqlite`.
- Custom Pydantic models and Enums are registered with `JsonPlusSerializer(allowed_msgpack_modules=...)` to ensure secure, warning-free serialization.
- Execution interrupts automatically after `human_review` using LangGraph's native `interrupt_after=["human_review"]`.
- When resumed in a new process, LangGraph restores the exact thread snapshot via `thread_id` and continues directly to `complete` without re-evaluating or revising previously processed nodes.

### Bounded Revisions & Idempotency Safeguards
- `max_revisions` is enforced dynamically during evaluation routing (`route_after_evaluation`). After 2 revision attempts, repeated `revise` decisions route immediately to the terminal node `revision_limit_reached`.
- The `complete` node inspects existing workflow status and past completion events; duplicate approvals log a `duplicate_approval_ignored` event and produce no secondary side effects.

---

## 3. Setup & Installation

### Prerequisites
- Python 3.11 or newer (Python 3.13 tested and verified)
- PowerShell (Windows) or bash (Linux/macOS)

### Virtual Environment Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r src/task-4_rk0802p/requirements.txt
```

---

## 4. Running the CLI

Run workflow commands from PowerShell or terminal:

```powershell
$env:PYTHONPATH = "src/task-4_rk0802p"

# 1. Start a workflow (reaches human review and pauses)
python -m workflow.cli run content-001 --scenario one_revision_then_pass

# 2. Inspect the saved checkpoint across process restarts
python -m workflow.cli resume content-001

# 3. Approve the workflow to resume and complete
python -m workflow.cli approve content-001

# 4. Duplicate approval (verify idempotency)
python -m workflow.cli approve content-001
```

---

## 5. Running Automated Tests

Run the full test suite with verbose output:
```powershell
.\.venv\Scripts\python.exe -m pytest src/task-4_rk0802p/tests -v
```

All 6 core task scenarios are covered:
1. `test_normal_pass_reaches_checkpoint_and_completes`
2. `test_one_revision_then_pass`
3. `test_stops_after_two_revisions`
4. `test_checkpoint_persists_to_sqlite_and_resumes_without_rerunning_work`
5. `test_subprocess_restart_resumption`
6. `test_duplicate_approval_does_not_repeat_completion`
7. `TestMalformedInputFailures` (input and schema failure tests)

---

## 6. End-to-End Demonstration Script

To execute a full end-to-end scripted run demonstrating run, pause, inspect, resume, approve, duplicate approval, and inspectable event logs:

```powershell
powershell -ExecutionPolicy Bypass -File src/task-4_rk0802p/examples/demo.ps1
```

---

## 7. Known Limitations

1. **Local Concurrency**: SQLite checkpointing uses standard locking suitable for single-node local execution. High-throughput distributed workers would benefit from PostgreSQL-backed checkpointers.
2. **Deterministic Evaluation**: Evaluators use static JSON fixtures (`fixtures/evaluator_scenarios.json`) rather than live LLMs, fulfilling the prompt requirement for offline reproducibility.

---

## 8. Acceptance Criteria Checklist

- [x] **Phase 1: Typed Workflow Contracts** — Pydantic models for content item, evaluator response, workflow state, and event records. Validation check passes for malformed content and unknown decisions.
- [x] **Phase 2: LangGraph Workflow** — Explicit nodes and conditional routing for evaluate, revise, human_review, and complete. Deterministic fixture sequences verify normal pass, one revision, and retry limit.
- [x] **Phase 3: Persistent Checkpoints** — SQLite-backed checkpointer with process restart resumption.
- [x] **Phase 4: CLI Interface** — `run`, `resume`, and `approve` commands.
- [x] **Phase 5: Bounded Revisions & Idempotency** — Strict 2-revision limit and safe duplicate approvals.
- [x] **Phase 6: End-to-End Demonstration** — Complete demo script and test verification.
