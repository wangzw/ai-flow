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
    """Goal got agent-ready: invoke Planner and reconcile, then drive child tasks
    inline. We orchestrate the entire flow in-process because GITHUB_TOKEN-driven
    events do NOT trigger downstream workflow runs (a known GH Actions limit)."""
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

    # Reconciler may have closed the goal already (status=done path).
    issue = repo.get_issue(issue.number)
    if "agent-done" in _label_names(issue) or "needs-human" in _label_names(issue):
        return 0

    return _drive_to_completion(repo=repo, goal_issue=issue, gh=gh, cfg=cfg)


def _drive_to_completion(*, repo, goal_issue, gh: GitHubClient, cfg: Config,
                         max_loops: int = 20) -> int:
    """Inline orchestration: dispatch ready tasks → review their PRs →
    merge-queue → re-enter Planner on child_done. Loops until the goal
    settles into agent-done / needs-human, or max_loops is reached."""
    from flow.handlers.pr_handler import review_pr
    from flow.manifest import GoalBody
    from flow.merge_queue import process_merge_queue
    from flow.planner import build_input_bundle, run_planner
    from flow.reconciler import gather_current_children, reconcile

    for loop in range(max_loops):
        print(f"[drive] loop {loop + 1}/{max_loops} goal=#{goal_issue.number}", flush=True)
        goal_issue = repo.get_issue(goal_issue.number)
        goal_body = GoalBody.parse(goal_issue.body or "")
        children = gather_current_children(repo, goal_body)
        progress = False

        # 1) Dispatch any agent-ready tasks whose deps are satisfied
        for child in children:
            if child.state_label != "agent-ready":
                continue
            unmet = [d for d in (child.body.deps or []) if not _is_dep_done(d, children)]
            if unmet:
                continue
            print(f"[drive] running implementer on task #{child.issue.number}",
                  flush=True)
            _run_implementer_for_task(
                repo=repo, task_issue=child.issue, task_body=child.body,
                gh=gh, cfg=cfg)
            progress = True

        # Refresh after implementer run
        children = gather_current_children(repo, goal_body)

        # 2) Review any open PRs linked to our tasks (state agent-working)
        for child in children:
            if child.state_label != "agent-working":
                continue
            pr = _find_pr_for_task(repo, child.body)
            if pr is None or pr.state != "open" or pr.draft:
                continue
            already_queued = any(lbl.name == "merge-queued" for lbl in pr.labels)
            if already_queued:
                continue
            print(f"[drive] reviewing PR #{pr.number} for task #{child.issue.number}",
                  flush=True)
            review_pr(pr=pr, repo=repo, gh=gh, cfg=cfg)
            progress = True

        # 3) Process merge queue
        merged = process_merge_queue(repo=repo, client=gh)
        if merged:
            print(f"[drive] merge_queue merged {merged} PR(s)", flush=True)
            progress = True

        # Refresh state after merges
        goal_issue = repo.get_issue(goal_issue.number)
        if "agent-done" in _label_names(goal_issue) or "needs-human" in _label_names(goal_issue):
            print("[drive] goal terminal; exiting", flush=True)
            return 0

        # 4) If all tasks terminal and progress was made, re-enter Planner
        goal_body = GoalBody.parse(goal_issue.body or "")
        children = gather_current_children(repo, goal_body)
        all_terminal = children and all(
            c.state_label in {"agent-done", "agent-failed"} for c in children
        )
        any_done = any(c.state_label == "agent-done" for c in children)
        if all_terminal and any_done:
            print("[drive] all tasks terminal → Planner re-entry", flush=True)
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
                invocation_reason="child_done",
                goal_issue=goal_issue, goal_body=goal_body,
                children=children_payload,
                repo_context={"default_branch": repo.default_branch},
                authoring_user=getattr(goal_issue.user, "login", None),
            )
            planner_client = _make_client_for("planner", cfg)
            result = run_planner(
                repo=repo, goal_issue_number=goal_issue.number,
                input_bundle=bundle, base_branch=repo.default_branch,
                client=planner_client,
            )
            if result.status == "no_marker":
                gh.comment(goal_issue,
                           f"❌ Planner 未产出 result.yaml（failed-env）：{result.blocker}")
                gh.set_state_label(goal_issue, "needs-human")
                return 0
            reconcile(
                planner_result=result, repo=repo, goal_issue=goal_issue,
                goal_body=goal_body,
                current_children=gather_current_children(repo, goal_body),
                client=gh, base_branch=repo.default_branch,
            )
            progress = True
            continue

        if not progress:
            print("[drive] no progress this loop; halting", flush=True)
            break

    return 0


def _is_dep_done(task_id: str, children) -> bool:
    for c in children:
        if c.task_id == task_id:
            return c.state_label == "agent-done"
    return False


def _find_pr_for_task(repo, task_body):
    """Find the open PR opened by Implementer for this task (matches branch
    or `Closes #<task_issue>`)."""
    for art in (task_body.artifacts or []):
        n = art.get("pr") if isinstance(art, dict) else None
        if n:
            try:
                return repo.get_pull(int(n))
            except Exception:
                pass
    return None


def _run_implementer_for_task(*, repo, task_issue, task_body, gh: GitHubClient,
                              cfg: Config) -> None:
    from flow.coder import run_implementer

    if not task_body.task_id:
        gh.comment(task_issue,
                   "❌ Task body 缺少 frontmatter (task_id)。需 Planner 重新生成。")
        gh.set_state_label(task_issue, "needs-human")
        return

    goal_prose = ""
    sibling_artifacts: list[dict] = []
    if task_body.goal_issue:
        try:
            goal_issue = repo.get_issue(task_body.goal_issue)
            gb = GoalBody.parse(goal_issue.body or "")
            goal_prose = gb.prose
            for entry in gb.manifest:
                if entry.task_id == task_body.task_id or entry.state != "agent-done":
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

    gh.set_state_label(task_issue, "agent-working")
    impl_client = _make_client_for("implementer", cfg)
    result = run_implementer(
        repo=repo, task_issue=task_issue, task_body=task_body,
        goal_issue_number=task_body.goal_issue,
        goal_prose=goal_prose, sibling_artifacts=sibling_artifacts,
        base_branch=repo.default_branch, client=impl_client,
        decision_response=task_body.agent_state.decision_response,
    )

    if result.status == "done":
        task_body.agent_state.stage = "reviewer"
        task_body.agent_state.progress = result.summary
        if result.pr_number:
            task_body.artifacts.append({"pr": result.pr_number,
                                        "branch": result.branch_name})
        gh.update_issue_body(task_issue, task_body.to_body())
        return

    if result.status == "blocked":
        from flow.comment_writer import build_needs_human_comment

        blocker = result.blocker or {}
        gh.comment(
            task_issue,
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
        task_body.agent_state.stage = "blocked"
        task_body.agent_state.blocker_type = blocker.get("type")
        task_body.agent_state.blocker_details = blocker
        gh.update_issue_body(task_issue, task_body.to_body())
        gh.set_state_label(task_issue, "needs-human")
        emit(EVENTS.CODER_BLOCKER, issue_iid=task_issue.number,
             blocker_type=blocker.get("type"))
        return

    # subprocess_error / no_marker → failed-env
    from flow.retry import classify_blocker, compute_next_attempt

    blocker = result.blocker or {}
    category = classify_blocker(
        stdout=str(blocker.get("stdout", "")),
        stderr=str(blocker.get("stderr", "")),
        returncode=int(blocker.get("returncode", 1) or 1),
    )
    prev = task_body.agent_state.failed_env or {}
    next_at, state = compute_next_attempt(
        category=category,
        attempt=int(prev.get("attempts", 0) or 0),
        retry_config=cfg.retry,
    )
    task_body.agent_state.failed_env = state
    if next_at is None:
        gh.comment(task_issue,
                   f"❌ failed-env (`{category}`) 已耗尽重试预算，需要人工介入。")
        gh.set_state_label(task_issue, "needs-human")
    else:
        gh.comment(task_issue,
                   f"⏳ failed-env (`{category}`)，将在 `{next_at.isoformat()}` 自动重试。")
        gh.set_state_label(task_issue, "agent-ready")
    task_body.agent_state.stage = "blocked"
    gh.update_issue_body(task_issue, task_body.to_body())


def handle_task_ready(*, repo, issue, gh: GitHubClient, cfg: Config) -> int:
    """Task got agent-ready directly: run implementer, then route to goal-driven
    orchestration so the rest of the chain (review→merge→re-plan) executes."""
    print(f"[task] #{issue.number} {issue.title!r}", flush=True)
    body = TaskBody.parse(issue.body or "")
    _run_implementer_for_task(repo=repo, task_issue=issue, task_body=body,
                              gh=gh, cfg=cfg)
    if body.goal_issue:
        try:
            goal_issue = repo.get_issue(body.goal_issue)
            return _drive_to_completion(repo=repo, goal_issue=goal_issue,
                                        gh=gh, cfg=cfg)
        except Exception:
            return 0
    return 0


def handle_issue_labeled() -> int:
    """Entry from workflow: read SW_* env, route to goal/task handler."""
    label = os.environ.get("SW_LABEL_ADDED")
    if label != "agent-ready":
        return 0

    cfg = Config.load()
    gh = GitHubClient.from_env()
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
