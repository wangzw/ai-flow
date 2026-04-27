import re
from typing import Callable

from sw.reviewer_stub import run_review_matrix

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
        # MVP: leave for future "agent-fixing"-style loop. For now, do nothing.
        return

    # ff-merge — rebase before merge to keep linear history (per spec §5.5)
    mr.rebase()
    mr.merge(merge_when_pipeline_succeeds=False, should_remove_source_branch=True)

    issue_iid = _extract_closing_issue_iid(mr.description)
    if issue_iid is None:
        return
    issue = project.issues.get(issue_iid)
    client.set_state_label(issue, "agent-done")
