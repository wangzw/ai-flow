"""Merge Queue processor for GitHub.

Pops PRs labeled `merge-queued` in FIFO order, runs Reviewer matrix, and
ff-merges via GitHub's atomic rebase-merge. Serialized at the workflow level
via Actions `concurrency:` group (see .github/workflows/agent-merge-queue.yml).

Spec: §6.2.
"""

import re
from typing import Callable

from sw.reviewer import run_review_matrix


class MergeQueueError(RuntimeError):
    """Raised on unrecoverable queue-processing failure."""


_CLOSES_RE = re.compile(r"closes\s+#(\d+)", re.IGNORECASE)
QUEUE_LABEL = "merge-queued"


def _extract_closing_issue_number(pr_body: str) -> int | None:
    m = _CLOSES_RE.search(pr_body or "")
    return int(m.group(1)) if m else None


def _has_label(pr, name: str) -> bool:
    return any(lbl.name == name for lbl in pr.labels)


def process_merge_queue_gh(
    *,
    repo,
    client,
    reviewer: Callable | None = None,
) -> int:
    """Pop the head of the merge queue and process it. Returns # processed (0 or 1)."""
    reviewer = reviewer or (lambda **kw: run_review_matrix(**kw))

    open_prs = repo.get_pulls(state="open")
    queued = [pr for pr in open_prs if _has_label(pr, QUEUE_LABEL)]
    if not queued:
        print("[merge_queue] queue empty — nothing to do", flush=True)
        return 0

    queued_sorted = sorted(
        queued, key=lambda p: (getattr(p, "created_at", ""), getattr(p, "number", 0))
    )
    head = queued_sorted[0]
    print(
        f"[merge_queue] {len(queued)} queued; popping FIFO head PR #{head.number}",
        flush=True,
    )

    print(f"[merge_queue] re-running reviewer matrix on PR #{head.number}...", flush=True)
    result = reviewer(
        mr_iid=head.number,
        project_path=repo.full_name,
        repo_path=None,
    )

    if not result.all_passed:
        print(
            f"[merge_queue] re-review FAILED ({result.failed_dimensions}); dequeueing",
            flush=True,
        )
        head.remove_from_labels(QUEUE_LABEL)
        issue_num = _extract_closing_issue_number(head.body)
        if issue_num is not None:
            issue = repo.get_issue(issue_num)
            client.set_state_label(issue, "agent-working")
        return 1

    print(f"[merge_queue] re-review PASSED; ff-merging PR #{head.number}...", flush=True)
    head.merge(
        merge_method="rebase",
        commit_title=f"Merge PR #{head.number}",
        delete_branch=True,
    )
    print(f"[merge_queue] PR #{head.number} merged", flush=True)

    issue_num = _extract_closing_issue_number(head.body)
    if issue_num is not None:
        issue = repo.get_issue(issue_num)
        client.set_state_label(issue, "agent-done")

    return 1
