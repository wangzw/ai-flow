import re
from typing import Callable

from sw.metrics import EVENTS, emit
from sw.reviewer import run_review_matrix

_CLOSES_RE = re.compile(r"closes\s+#(\d+)", re.IGNORECASE)


def _extract_closing_issue_iid(mr_description: str) -> int | None:
    m = _CLOSES_RE.search(mr_description or "")
    return int(m.group(1)) if m else None


def handle_mr_ready(
    *,
    project,
    mr_iid: int,
    client,
    reviewer: Callable | None = None,
) -> None:
    """Run the Reviewer matrix on a ready MR. On all-pass: ff-merge + Issue done."""
    reviewer = reviewer or (lambda **kw: run_review_matrix(**kw))

    mr = project.mergerequests.get(mr_iid)
    result = reviewer(mr_iid=mr_iid, project_path=project.path_with_namespace)

    if not result.all_passed:
        emit(EVENTS.REVIEWER_FAILED, mr_iid=mr_iid, failed_dimensions=result.failed_dimensions)
        # MVP: leave for future "agent-fixing"-style loop. For now, do nothing.
        return

    emit(EVENTS.REVIEWER_PASSED, mr_iid=mr_iid, failed_dimensions=result.failed_dimensions)

    # All MUST dimensions PASS — enqueue for serial merge processing.
    # The merge queue (sw.merge_queue.process_merge_queue) handles rebase + re-review + ff-merge.
    if "merge-queued" not in mr.labels:
        mr.labels = [*mr.labels, "merge-queued"]
        mr.save()
        emit(EVENTS.ENQUEUED, mr_iid=mr_iid)
