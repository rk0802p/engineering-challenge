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

### Typed Workflow Contracts (Phase 1)
- `ContentItem`: Validates draft content (`content_id`, `title`, `body`, `metadata`). Rejects empty or whitespace-only inputs and forbids unauthorized fields.
- `EvaluatorResponse`: Enforces deterministic decisions (`revise` or `human_review`), optional normalized quality score `[0.0, 1.0]`, and feedback notes. Any unknown decision fails validation immediately.
- `WorkflowState`: Preserves workflow execution state (`run_id`, `content_id`, `content`, `status`, `revision_count`, `max_revisions`, `evaluation_result`, `checkpoint_version`).
- `WorkflowEvent`: Structured audit event record with unique event ID, timestamp, stage, and payload for deterministic event log reconstruction.

---

## 3. Setup & Installation

### Prerequisites
- Python 3.11 or newer (Python 3.13 supported)
- PowerShell (Windows) or bash (Linux/macOS)

### Virtual Environment Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r src/task-4_rk0802p/requirements.txt
```

---

## 4. Running Tests

Run the full test suite with verbose output:
```powershell
.\.venv\Scripts\python.exe -m pytest src/task-4_rk0802p/tests -v
```

---

## 5. Acceptance Criteria Checklist

- [x] **Phase 1: Typed Workflow Contracts** — Pydantic models for content item, evaluator response, workflow state, and event records. Validation check passes for malformed content and unknown decisions.
- [ ] **Phase 2: LangGraph Workflow** — Explicit nodes and conditional routing for evaluate, revise, human_review, and complete.
- [ ] **Phase 3: Persistent Checkpoints** — SQLite-backed checkpointer with process restart resumption.
- [ ] **Phase 4: CLI Interface** — `run`, `resume`, and `approve` commands.
- [ ] **Phase 5: Bounded Revisions & Idempotency** — Strict 2-revision limit and safe duplicate approvals.
- [ ] **Phase 6: End-to-End Demonstration** — Complete demo script and test verification.
