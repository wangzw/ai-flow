# Real Reviewer Matrix Implementation Plan

**Goal:** Replace `reviewer_stub.py` (always-PASS) with `reviewer.py` that uses **Claude Code CLI** to review an MR's diff against the 7 MUST dimensions per spec §5. Single-Agent **sequential** mode (spec §5.3 implementation (a)) — each dimension is a separate Claude Code invocation with a dimension-specific system prompt; results aggregated.

**Architecture:**
- New `reviewer.py` orchestrates 7 sequential Claude Code calls
- For each dimension: build dimension-specific prompt → invoke Claude → parse `.review/{dimension}.yaml` marker → record PASS/FAIL+reason
- Aggregate into `ReviewResult` (compatible with existing handler)
- `reviewer_stub.py` renamed to `reviewer_fake.py` for testing
- `mr_handler` switched to import from `reviewer`

**Key spec constraints honored:**
- Reviewer reads only AC + diff + tests + code comments (NOT commit messages) — spec §5.3
- Each dimension uses a different system prompt (异构 across dimensions inside the same Agent)
- Coder vs Reviewer 异构 maintained via role-distinct prompts (Coder = builder, Reviewer = adversarial auditor)

## DECISIONS (defaults)

1. **Sequential vs subagent**: Sequential. Simplest to implement; addable later via parallel subagent dispatch.
2. **Per-dimension prompt**: Each dimension has its own system prompt + scoring rubric. Common envelope (AC, diff context, "you may NOT read commit messages") plus dimension-specific guidance.
3. **Diff context**: We pass the MR diff via `git diff <base>..<source>` output. The Coder's commit messages are explicitly excluded from this view.
4. **Failure mode**: If a dimension review fails to produce a marker → treat as FAIL with `reason: "no marker produced"`. Fail-closed.
5. **Performance/Migration NoOp**: When the diff has no schema/migration files, Migration Safety reviewer auto-PASSes (NoOp); when no perf basis exists, Performance reviewer auto-PASSes with `reason: "no baseline"`.

## Tasks

### Task 1: Implement `reviewer.py` (TDD)

**Files:** Create `src/sw/reviewer.py`, `tests/sw/test_reviewer.py`.

The `run_review_matrix(*, mr_iid, project_path, claude=None, repo_path=None)` function:
- Iterates through `MUST_DIMENSIONS`
- For each dim, invokes Claude Code with the dim's prompt in `repo_path`
- Reads `.review/<dim>.yaml` for `result: PASS|FAIL` + `reason`
- Returns aggregated `ReviewResult`

Tests mock `ClaudeCodeClient` and filesystem markers.

### Task 2: Rename `reviewer_stub.py` → `reviewer_fake.py`

`git mv` + update `tests/sw/test_reviewer_stub.py` → `test_reviewer_fake.py` + fix imports.

### Task 3: Update `mr_handler` to import from real `reviewer`

`from sw.reviewer_stub import run_review_matrix` → `from sw.reviewer import run_review_matrix`.

Verify all handler tests inject `reviewer=` mocks (they should). Run full suite.

### Task 4: Tag

`git tag -a v0.3.0-real-reviewer -m "Real Reviewer Matrix using Claude Code CLI"`

## Acceptance

- 79 → ~85 tests; coverage stays ≥ 88%
- ruff clean
- `mr_handler` integration test still green (uses fake reviewer with all-PASS)
- Tag at HEAD
