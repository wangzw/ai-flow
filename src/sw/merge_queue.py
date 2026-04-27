"""Merge Queue processor for GitLab CE.

Pops MRs labeled `merge-queued` in FIFO order, rebases each, re-runs the
Reviewer matrix, and ff-merges. Serialized via GitLab CI `resource_group`
(see ci/gitlab-ci.yml `merge_queue_event` job).

Spec: §6.2 (合并队列), §7.5 (CE: resource_group 替代 Merge Trains).
"""

import re
import time
from typing import Callable

from sw.reviewer import run_review_matrix


class MergeQueueError(RuntimeError):
    """Raised on unrecoverable queue-processing failure (e.g., rebase timeout)."""


_CLOSES_RE = re.compile(r"closes\s+#(\d+)", re.IGNORECASE)
QUEUE_LABEL = "merge-queued"


def _extract_closing_issue_iid(mr_description: str) -> int | None:
    m = _CLOSES_RE.search(mr_description or "")
    return int(m.group(1)) if m else None


def _wait_for_rebase(
    project,
    mr_iid: int,
    *,
    sleep: Callable[[float], None],
    timeout: float,
    poll_interval: float,
):
    """Poll mr.rebase_in_progress until False or timeout. Returns the refreshed mr."""
    deadline = time.monotonic() + timeout
    last_mr = None
    while time.monotonic() < deadline:
        last_mr = project.mergerequests.get(mr_iid)
        if not getattr(last_mr, "rebase_in_progress", False):
            return last_mr
        sleep(poll_interval)
    raise MergeQueueError(
        f"rebase did not complete within {timeout}s for MR {mr_iid}"
    )


def process_merge_queue(
    *,
    project,
    client,
    reviewer: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rebase_timeout: float = 60.0,
    rebase_poll_interval: float = 2.0,
) -> int:
    """Pop the head of the merge queue and process it. Returns # processed (0 or 1)."""
    reviewer = reviewer or (lambda **kw: run_review_matrix(**kw))

    candidates = project.mergerequests.list(labels=[QUEUE_LABEL], state="opened", get_all=True)
    if not candidates:
        return 0

    # FIFO by created_at, ties by iid
    candidates_sorted = sorted(
        candidates,
        key=lambda m: (getattr(m, "created_at", ""), getattr(m, "iid", 0)),
    )
    head = candidates_sorted[0]
    head_iid = head.iid

    # Trigger rebase, then poll for completion
    head.rebase()
    refreshed = _wait_for_rebase(
        project,
        head_iid,
        sleep=sleep,
        timeout=rebase_timeout,
        poll_interval=rebase_poll_interval,
    )

    result = reviewer(
        mr_iid=head_iid,
        project_path=project.path_with_namespace,
        repo_path=None,
    )

    if not result.all_passed:
        # Remove merge-queued label, reset Issue to agent-working
        if QUEUE_LABEL in refreshed.labels:
            refreshed.labels = [lbl for lbl in refreshed.labels if lbl != QUEUE_LABEL]
        refreshed.save()
        issue_iid = _extract_closing_issue_iid(refreshed.description)
        if issue_iid is not None:
            issue = project.issues.get(issue_iid)
            client.set_state_label(issue, "agent-working")
        return 1

    # All pass — merge
    refreshed.merge(merge_when_pipeline_succeeds=False, should_remove_source_branch=True)

    issue_iid = _extract_closing_issue_iid(refreshed.description)
    if issue_iid is not None:
        issue = project.issues.get(issue_iid)
        client.set_state_label(issue, "agent-done")

    return 1
