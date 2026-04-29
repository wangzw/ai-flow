"""workflow_dispatch helper — fires downstream Actions runs.

GITHUB_TOKEN-driven mutations (issue creation, label add, pr-create) do not
fan out new workflow runs. To chain Planner→Implementer→Reviewer→Merge as
separate Actions jobs, we explicitly call the workflow_dispatch endpoint
with ACTION_GITHUB_TOKEN (actions:write).

Falls back to a no-op + log when ACTION_GITHUB_TOKEN is missing — the
caller can still rely on the sync orchestrator path in that case.
"""

from __future__ import annotations

import os
from typing import Optional


def _action_token() -> Optional[str]:
    return os.environ.get("ACTION_GITHUB_TOKEN")


def is_available() -> bool:
    return bool(_action_token())


def dispatch(
    *,
    repo_full_name: str,
    workflow_filename: str,
    inputs: dict,
    ref: str = "main",
) -> bool:
    """Trigger a workflow_dispatch event. Returns True on 204 success."""
    token = _action_token()
    if not token:
        print(f"[dispatch] ACTION_GITHUB_TOKEN missing; cannot trigger {workflow_filename}",
              flush=True)
        return False

    from github import Github

    gh = Github(token)
    try:
        repo = gh.get_repo(repo_full_name)
        wf = repo.get_workflow(workflow_filename)
        ok = wf.create_dispatch(ref=ref, inputs={k: str(v) for k, v in inputs.items()})
    except Exception as exc:
        print(f"[dispatch] {workflow_filename} {inputs} failed: {exc}", flush=True)
        return False
    print(f"[dispatch] -> {workflow_filename} inputs={inputs} ok={ok}", flush=True)
    return bool(ok)


def dispatch_issue(repo_full_name: str, issue_number: int) -> bool:
    """Trigger flow-issue.yml for a goal- or task-typed Issue."""
    return dispatch(
        repo_full_name=repo_full_name,
        workflow_filename="flow-issue.yml",
        inputs={"issue_number": issue_number},
    )


def dispatch_pr_ready(repo_full_name: str, pr_number: int) -> bool:
    """Trigger flow-pr-ready.yml for a PR opened by Implementer."""
    return dispatch(
        repo_full_name=repo_full_name,
        workflow_filename="flow-pr-ready.yml",
        inputs={"pr_number": pr_number},
    )


def dispatch_merge_queue(repo_full_name: str) -> bool:
    """Trigger flow-merge-queue.yml to drain the queue."""
    return dispatch(
        repo_full_name=repo_full_name,
        workflow_filename="flow-merge-queue.yml",
        inputs={},
    )
