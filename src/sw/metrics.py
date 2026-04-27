"""Structured metrics emission for the AI Coding Workflow.

Emits one JSON line per event. Sink is stdout by default; if SW_METRICS_FILE
is set, appends to that file. Errors during emission are swallowed — metrics
must never break the workflow.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


class EVENTS:
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


def emit(event: str, *, issue_iid: int | None = None, **fields: Any) -> None:
    """Emit a structured metrics event. Never raises."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "issue_iid": issue_iid,
        "fields": fields,
    }
    line = json.dumps(record, ensure_ascii=False)
    sink = os.environ.get("SW_METRICS_FILE")
    try:
        if sink:
            with open(sink, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line, file=sys.stdout)
    except Exception:
        # Never break the workflow. Metrics are best-effort.
        pass
