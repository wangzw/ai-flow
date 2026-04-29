"""Merge queue processor (spec §6.2).

After a PR passes all MUST review dimensions and is labeled `merge-queued`,
this module pops the FIFO head, re-runs reviewer (defense in depth), and
ff-merges via GitHub's atomic rebase-merge. Serialized at the workflow level
via Actions `concurrency:` group.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Callable

from flow.clients.copilot import CopilotCliClient
from flow.coder import _clone_repo  # reuse helper
from flow.manifest import TaskBody
from flow.metrics import EVENTS, emit
from flow.reviewer import run_review_matrix

_CLOSES_RE = re.compile(r"closes\s+#(\d+)", re.IGNORECASE)
QUEUE_LABEL = "merge-queued"


def _extract_closing_issue_number(pr_body: str) -> int | None:
    m = _CLOSES_RE.search(pr_body or "")
    return int(m.group(1)) if m else None


def _has_label(pr, name: str) -> bool:
    return any(lbl.name == name for lbl in pr.labels)


def process_merge_queue(
    *,
    repo,
    client,
    reviewer: Callable | None = None,
    re_review: bool = True,
) -> int:
    """Pop the head of the merge queue and process it. Returns # processed (0 or 1)."""
    open_prs = list(repo.get_pulls(state="open"))
    queued = [pr for pr in open_prs if _has_label(pr, QUEUE_LABEL)]
    if not queued:
        print("[merge_queue] queue empty", flush=True)
        return 0

    queued_sorted = sorted(
        queued, key=lambda p: (getattr(p, "created_at", ""), getattr(p, "number", 0))
    )
    head = queued_sorted[0]
    print(f"[merge_queue] {len(queued)} queued; popping FIFO head PR #{head.number}",
          flush=True)
    emit(EVENTS.QUEUE_POP, pr_number=head.number, queue_size=len(queued))

    if re_review:
        workdir = Path(tempfile.mkdtemp(prefix=f"flow-merge-pr-{head.number}-"))
        repo_path = workdir / "repo"
        sw_git_token = os.environ.get("SW_GIT_TOKEN") or os.environ.get("COPILOT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if sw_git_token and repo.clone_url.startswith("https://"):
            clone_url = repo.clone_url.replace(
                "https://", f"https://x-access-token:{sw_git_token}@", 1
            )
        else:
            clone_url = repo.clone_url

        try:
            _clone_repo(clone_url, repo_path, branch=head.head.ref)
        except Exception as exc:
            print(f"[merge_queue] clone failed: {exc}; dequeueing", flush=True)
            head.remove_from_labels(QUEUE_LABEL)
            return 1

        # Look up task to get its spec; if no link, use a permissive empty spec
        task_issue_number = _extract_closing_issue_number(head.body or "")
        task_spec: dict = {}
        task_id = f"PR-{head.number}"
        if task_issue_number is not None:
            try:
                task_issue = repo.get_issue(task_issue_number)
                tb = TaskBody.parse(task_issue.body or "")
                task_spec = tb.spec.to_dict()
                task_id = tb.task_id or task_id
            except Exception:
                pass

        cli = (reviewer or CopilotCliClient)()  # type: ignore[operator]
        result = run_review_matrix(
            pr_number=head.number,
            task_id=task_id,
            task_spec=task_spec,
            repo_path=repo_path,
            client=cli,
            base_branch=head.base.ref,
            iteration=999,  # tag re-review
        )
        if not result.all_must_passed:
            print(
                f"[merge_queue] re-review FAILED ({result.failed_dimensions}); dequeueing",
                flush=True,
            )
            head.remove_from_labels(QUEUE_LABEL)
            if task_issue_number is not None:
                try:
                    issue = repo.get_issue(task_issue_number)
                    client.set_state_label(issue, "agent-working")
                except Exception:
                    pass
            return 1

    print(f"[merge_queue] merging PR #{head.number}...", flush=True)
    head.merge(
        merge_method="rebase",
        commit_title=f"Merge PR #{head.number}",
        delete_branch=True,
    )
    emit(EVENTS.MERGED, pr_number=head.number)

    # Transition the linked task to agent-done; the cron / scheduled workflow
    # picks up `child_done` and re-invokes the Planner.
    task_issue_number = _extract_closing_issue_number(head.body or "")
    if task_issue_number is not None:
        try:
            issue = repo.get_issue(task_issue_number)
            client.set_state_label(issue, "agent-done")
            tb = TaskBody.parse(issue.body or "")
            tb.artifacts.append({"pr": head.number, "branch": head.head.ref})
            client.update_issue_body(issue, tb.to_body())

            # Find parent goal and add it to the planner re-entry queue
            goal_num = tb.goal_issue
            if goal_num:
                try:
                    goal_issue = repo.get_issue(goal_num)
                    # Trigger Planner re-entry by toggling label back to agent-working
                    # so cron picks it up — simpler: just emit metric and let cron sweep.
                    emit(EVENTS.PLANNER_RECONCILED, issue_iid=goal_num,
                         reason="child_done", child=task_issue_number)
                    # Best-effort: nudge the goal back to agent-working so the
                    # cron workflow re-invokes Planner with reason=child_done.
                    if not any(lbl.name == "agent-working" for lbl in goal_issue.labels):
                        client.set_state_label(goal_issue, "agent-working")
                except Exception:
                    pass
        except Exception:
            pass
    return 1
