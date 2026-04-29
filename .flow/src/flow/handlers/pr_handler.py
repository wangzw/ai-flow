"""PR ready_for_review handler (spec §7).

Runs Reviewer matrix; on PASS, adds `merge-queued`; on FAIL, applies the
three-stage escalation policy (auto-retry → Planner arbitration → needs-human).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from flow.clients.github import GitHubClient
from flow.coder import _clone_repo
from flow.config import Config
from flow.manifest import TaskBody
from flow.metrics import EVENTS, emit

_CLOSES_RE_IMPORT = None


def _link_task(repo, pr_body: str):
    import re
    m = re.search(r"closes\s+#(\d+)", pr_body or "", re.IGNORECASE)
    if not m:
        return None
    try:
        return repo.get_issue(int(m.group(1)))
    except Exception:
        return None


def review_pr(*, pr, repo, gh: GitHubClient, cfg: Config) -> int:
    """Run reviewer for a PR; mirrors handle_pr_ready but works in-process."""
    from flow.clients.copilot import CopilotCliClient
    from flow.reviewer import run_review_matrix

    pr_number = pr.number
    task_issue = _link_task(repo, pr.body or "")
    task_id = "PR"
    task_spec: dict = {}
    body: TaskBody | None = None
    if task_issue is not None:
        body = TaskBody.parse(task_issue.body or "")
        task_id = body.task_id or f"PR-{pr_number}"
        task_spec = body.spec.to_dict()

    workdir = Path(tempfile.mkdtemp(prefix=f"flow-review-pr-{pr_number}-"))
    repo_path = workdir / "repo"
    sw_git_token = (os.environ.get("SW_GIT_TOKEN")
        or os.environ.get("COPILOT_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN"))
    if sw_git_token and repo.clone_url.startswith("https://"):
        clone_url = repo.clone_url.replace(
            "https://", f"https://x-access-token:{sw_git_token}@", 1
        )
    else:
        clone_url = repo.clone_url
    try:
        _clone_repo(clone_url, repo_path, branch=pr.head.ref)
    except Exception as exc:
        print(f"[pr_ready] clone failed: {exc}", flush=True)
        return 0

    iteration = 1
    if body is not None:
        iteration = body.review.iteration + 1
        body.review.iteration = iteration

    enabled_must = tuple(cfg.review.get("dimensions", {}).get("must", []))
    enabled_may = tuple(cfg.review.get("dimensions", {}).get("may", []))
    result = run_review_matrix(
        pr_number=pr_number,
        task_id=task_id,
        task_spec=task_spec,
        repo_path=repo_path,
        client=CopilotCliClient(),
        base_branch=pr.base.ref,
        iteration=iteration,
        enabled_must=enabled_must or None,  # type: ignore[arg-type]
        enabled_may=enabled_may,
        prior_history=body.review.history if body else [],
    )

    if body is not None:
        body.review.history.append({
            "iteration": iteration,
            "results": result.dimension_results,
            "reasons": result.reasons,
        })
        gh.update_issue_body(task_issue, body.to_body())

    if result.all_must_passed:
        if not any(lbl.name == "merge-queued" for lbl in pr.labels):
            pr.add_to_labels("merge-queued")
        emit(EVENTS.ENQUEUED, pr_number=pr_number)
        return 0

    max_iter = int((cfg.review.get("max_iterations") or 5))
    if iteration < max_iter and body is not None:
        if body.review.arbitrations < int(cfg.review.get("max_arbitrations", 2)):
            body.agent_state.stage = "implementer"
            body.agent_state.progress = (
                f"Reviewer iteration {iteration} failed: {result.failed_dimensions}; "
                f"reasons: {result.reasons}"
            )
            gh.update_issue_body(task_issue, body.to_body())
            gh.set_state_label(task_issue, "agent-ready")
            return 0
        body.review.arbitrations += 1
        gh.update_issue_body(task_issue, body.to_body())
        try:
            goal_issue = repo.get_issue(body.goal_issue)
            gh.comment(goal_issue,
                       f"⚖️ Reviewer 死循环 (iter={iteration}, dims={result.failed_dimensions})。"
                       "调度 Planner 仲裁。")
            gh.set_state_label(goal_issue, "agent-working")
        except Exception:
            pass
        return 0

    if task_issue is not None:
        gh.comment(task_issue,
                   f"❌ Reviewer 已达最大迭代 ({iteration})，dims={result.failed_dimensions}，"
                   "需要人工介入。")
        gh.set_state_label(task_issue, "needs-human")
    return 0


def handle_pr_ready() -> int:
    pr_number = int(os.environ["SW_PR_NUMBER"])
    cfg = Config.load()
    gh = GitHubClient.from_env()
    repo = gh.get_repo(os.environ["SW_REPO"])
    pr = repo.get_pull(pr_number)
    return review_pr(pr=pr, repo=repo, gh=gh, cfg=cfg)
