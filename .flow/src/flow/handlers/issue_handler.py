"""Issue label handler (spec §3.5, §5).

Routing on `agent-ready` label:
  - type:goal  → run Planner → reconcile
  - type:task  → run Implementer → wait for PR review/merge

The handler is invoked from .github/workflows/flow-issue.yml.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from flow.clients.github import GitHubClient
from flow.config import Config
from flow.manifest import GoalBody, TaskBody
from flow.metrics import EVENTS, emit


def _label_names(issue) -> list[str]:
    return [lbl.name for lbl in issue.labels]


def _is_goal(issue) -> bool:
    return "type:goal" in _label_names(issue)


def _is_task(issue) -> bool:
    return "type:task" in _label_names(issue)


def _make_client_for(role: str, cfg: Config):
    """Resolve agent client by role (planner/implementer/reviewer)."""
    from flow.clients.copilot import CopilotCliClient

    name = (cfg.models or {}).get(f"{role}_cli", "copilot")
    if name == "copilot":
        return CopilotCliClient()
    raise NotImplementedError(f"agent client {name!r} not yet supported")


def handle_goal_ready(*, repo, issue, gh: GitHubClient, cfg: Config) -> int:
    """Goal got agent-ready: invoke Planner and reconcile."""
    from flow.planner import build_input_bundle, run_planner
    from flow.reconciler import gather_current_children, reconcile

    print(f"[goal] #{issue.number} {issue.title!r}", flush=True)
    body = GoalBody.parse(issue.body or "")
    body.agent_state.stage = "planning"
    body.agent_state.last_planner_run = datetime.now(timezone.utc).isoformat()
    gh.set_state_label(issue, "agent-working")
    gh.update_issue_body(issue, body.to_body())

    children = gather_current_children(repo, body)
    children_payload = [
        {
            "issue": c.issue.number,
            "task_id": c.task_id,
            "state": c.state_label,
            "spec": c.body.spec.to_dict(),
            "deps": c.body.deps,
            "agent_state": c.body.agent_state.to_dict(),
            "review": c.body.review.to_dict(),
        }
        for c in children
    ]
    bundle = build_input_bundle(
        invocation_reason="initial" if not body.manifest else "child_done",
        goal_issue=issue,
        goal_body=body,
        children=children_payload,
        repo_context={"default_branch": repo.default_branch},
        authoring_user=getattr(issue.user, "login", None),
    )
    client = _make_client_for("planner", cfg)
    result = run_planner(
        repo=repo,
        goal_issue_number=issue.number,
        input_bundle=bundle,
        base_branch=repo.default_branch,
        client=client,
    )
    if result.status == "no_marker":
        gh.comment(
            issue,
            f"❌ Planner 未产出 result.yaml（failed-env）：{result.blocker}",
        )
        gh.set_state_label(issue, "needs-human")
        return 0

    reconcile(
        planner_result=result,
        repo=repo,
        goal_issue=issue,
        goal_body=body,
        current_children=gather_current_children(repo, body),
        client=gh,
        base_branch=repo.default_branch,
    )
    return 0


def handle_task_ready(*, repo, issue, gh: GitHubClient, cfg: Config) -> int:
    """Task got agent-ready: dispatch Implementer."""
    from flow.coder import run_implementer

    print(f"[task] #{issue.number} {issue.title!r}", flush=True)
    body = TaskBody.parse(issue.body or "")
    if not body.task_id:
        gh.comment(issue,
                   "❌ Task body 缺少 frontmatter (task_id)。需 Planner 重新生成。")
        gh.set_state_label(issue, "needs-human")
        return 0

    # Resolve goal prose for Planner-context injection
    goal_prose = ""
    sibling_artifacts: list[dict] = []
    if body.goal_issue:
        try:
            goal_issue = repo.get_issue(body.goal_issue)
            gb = GoalBody.parse(goal_issue.body or "")
            goal_prose = gb.prose
            for entry in gb.manifest:
                if entry.task_id == body.task_id or entry.state != "agent-done":
                    continue
                try:
                    si = repo.get_issue(entry.issue)
                    sb = TaskBody.parse(si.body or "")
                    sibling_artifacts.append({
                        "task_id": sb.task_id,
                        "summary": (sb.agent_state.progress or "")[:500],
                        "artifacts": sb.artifacts,
                    })
                except Exception:
                    continue
        except Exception:
            pass

    gh.set_state_label(issue, "agent-working")
    client = _make_client_for("implementer", cfg)
    result = run_implementer(
        repo=repo,
        task_issue=issue,
        task_body=body,
        goal_issue_number=body.goal_issue,
        goal_prose=goal_prose,
        sibling_artifacts=sibling_artifacts,
        base_branch=repo.default_branch,
        client=client,
        decision_response=body.agent_state.decision_response,
    )

    if result.status == "done":
        body.agent_state.stage = "reviewer"
        body.agent_state.progress = result.summary
        if result.pr_number:
            body.artifacts.append({"pr": result.pr_number, "branch": result.branch_name})
        gh.update_issue_body(issue, body.to_body())
        # Stay in agent-working; PR-ready event triggers reviewer.
        return 0

    if result.status == "blocked":
        from flow.comment_writer import build_needs_human_comment

        blocker = result.blocker or {}
        gh.comment(
            issue,
            build_needs_human_comment(
                prose=f"Implementer 阻塞：**{blocker.get('type', 'unknown')}** — "
                      f"{blocker.get('message', '')}",
                agent_state={"stage": "implementer",
                             "blocker_type": blocker.get("type", "unknown")},
                decision={
                    "question": blocker.get("question",
                                            "请提供决策或修正后回复 /agent resume"),
                    "options": blocker.get("options") or [],
                    "custom_allowed": True,
                },
            ),
        )
        body.agent_state.stage = "blocked"
        body.agent_state.blocker_type = blocker.get("type")
        body.agent_state.blocker_details = blocker
        gh.update_issue_body(issue, body.to_body())
        gh.set_state_label(issue, "needs-human")
        emit(EVENTS.CODER_BLOCKER, issue_iid=issue.number,
             blocker_type=blocker.get("type"))
        return 0

    # subprocess_error / no_marker → failed-env
    from flow.retry import classify_blocker, compute_next_attempt

    blocker = result.blocker or {}
    category = classify_blocker(
        stdout=str(blocker.get("stdout", "")),
        stderr=str(blocker.get("stderr", "")),
        returncode=int(blocker.get("returncode", 1) or 1),
    )
    prev = body.agent_state.failed_env or {}
    next_at, state = compute_next_attempt(
        category=category,
        attempt=int(prev.get("attempts", 0) or 0),
        retry_config=cfg.retry,
    )
    body.agent_state.failed_env = state
    if next_at is None:
        gh.comment(issue,
                   f"❌ failed-env (`{category}`) 已耗尽重试预算，需要人工介入。")
        gh.set_state_label(issue, "needs-human")
    else:
        gh.comment(issue,
                   f"⏳ failed-env (`{category}`)，将在 `{next_at.isoformat()}` 自动重试。")
        gh.set_state_label(issue, "agent-ready")
    body.agent_state.stage = "blocked"
    gh.update_issue_body(issue, body.to_body())
    return 0


def handle_issue_labeled() -> int:
    """Entry from workflow: read SW_* env, route to goal/task handler."""
    label = os.environ.get("SW_LABEL_ADDED")
    if label != "agent-ready":
        return 0

    cfg = Config.load()
    gh = GitHubClient.from_token(os.environ["GITHUB_TOKEN"])
    repo = gh.get_repo(os.environ["SW_REPO"])
    issue = repo.get_issue(int(os.environ["SW_ISSUE_NUMBER"]))

    if _is_goal(issue):
        return handle_goal_ready(repo=repo, issue=issue, gh=gh, cfg=cfg)
    if _is_task(issue):
        return handle_task_ready(repo=repo, issue=issue, gh=gh, cfg=cfg)

    # No type label — try to infer
    body = issue.body or ""
    if "schema_version" in body and "manifest" in body:
        return handle_goal_ready(repo=repo, issue=issue, gh=gh, cfg=cfg)
    print("[issue_handler] no type label; ignoring", file=sys.stderr, flush=True)
    return 0
