"""Structured metrics emission (spec §14, §16.5).

Emits one JSON line per event. Sink is stdout by default; if FLOW_METRICS_FILE
is set, appends to that file. emit() never raises (spec §14.5).
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


class EVENTS:
    LLM_CALL = "llm_call"
    STATE_TRANSITION = "state_transition"
    AC_VALIDATION = "ac_validation"
    CODER_DISPATCHED = "coder_dispatched"
    CODER_BLOCKER = "coder_blocker"
    REVIEWER_PASSED = "reviewer_passed"
    REVIEWER_FAILED = "reviewer_failed"
    ENQUEUED = "enqueued"
    MERGED = "merged"
    DEQUEUED = "dequeued"
    COMMAND_RECEIVED = "command_received"
    QUEUE_POP = "queue_pop"
    PLANNER_DISPATCHED = "planner_dispatched"
    PLANNER_BLOCKED = "planner_blocked"
    PLANNER_FALSE_DONE = "planner_false_done"
    PLANNER_RECONCILED = "planner_reconciled"
    GOAL_DONE = "goal_done"


def emit(event: str, *, issue_iid: int | None = None, **fields: Any) -> None:
    """Emit a structured metrics event. Never raises."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "issue_iid": issue_iid,
        "fields": fields,
    }
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        sink = os.environ.get("FLOW_METRICS_FILE")
        if sink:
            with open(sink, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line, file=sys.stdout, flush=True)
    except Exception:
        # Never break the workflow.
        pass


def emit_llm_call(
    *,
    role: str,
    goal: int | None,
    task_id: str | None,
    model: str,
    duration_ms: int,
    exit_status: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd_estimate: float | None = None,
    iteration: int | None = None,
) -> None:
    """Cost-observability event (spec §14.2). Never raises."""
    emit(
        EVENTS.LLM_CALL,
        role=role,
        goal=goal,
        task_id=task_id,
        model=model,
        duration_ms=duration_ms,
        exit_status=exit_status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd_estimate=cost_usd_estimate,
        iteration=iteration,
    )
