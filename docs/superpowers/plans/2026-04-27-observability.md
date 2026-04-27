# Observability Implementation Plan

**Goal:** Emit structured metrics for every state transition and Coder/Reviewer outcome; provide a CLI to compute aggregate statistics (automation rate, mean time-to-done, blocker frequency by type) from the metrics log.

**Architecture:**
- `metrics.py` — single function `emit(event_name, **fields)` writes a JSON line to a sink (stdout by default, file if `SW_METRICS_FILE` env set). Cheap, no external deps.
- Handlers + queue processor call `emit` at key points: state transitions, AC validation outcomes, Coder/Reviewer results, merge events.
- `report.py` — reads a metrics log and computes:
  - **Automation rate**: completed without ever entering `needs-human` ÷ total completed
  - **Mean time-to-done** (per-Issue duration)
  - **Blocker type histogram**

## DECISIONS

1. **Sink**: Append JSON lines to file when `SW_METRICS_FILE` set; else stdout. No remote/Prometheus push for MVP.
2. **Schema**: `{ "ts": "...", "event": "...", "issue_iid": ..., "fields": {...} }`. Stable enough for ad-hoc analysis.
3. **No global state**: emit() is pure (formats and writes; no buffer).
4. **Optionality**: emit() never raises; errors degrade silently. Metrics must not break the workflow.

## Tasks

### Task 1: `metrics.py` (TDD)

Functions:
- `emit(event: str, *, issue_iid: int | None = None, **fields)` — writes JSON line
- `EVENTS` — string constants for known events

### Task 2: Integrate emits into existing modules

- `issue_handler`: emit `ac_validation` (PASS/FAIL), `coder_dispatched`, `coder_blocker`
- `comment_handler`: emit `command_received`, `coder_dispatched`, `coder_blocker`
- `mr_handler`: emit `reviewer_passed` / `reviewer_failed`, `enqueued`
- `merge_queue`: emit `queue_pop`, `merged`, `dequeued`

### Task 3: `report.py` CLI (TDD)

`python -m sw.report <metrics-file>` → prints aggregates.

### Task 4: Tag

`v0.6.0-observability`
