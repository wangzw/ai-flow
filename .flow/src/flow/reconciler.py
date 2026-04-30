"""Reconciler: apply Planner result to the goal tree (spec §5.5).

Pure dispatcher — takes a PlannerResult + current tree, performs the set-based
create/update/cancel operations on the goal Issue + child task Issues.
"""

from __future__ import annotations

from dataclasses import dataclass

from flow.clients.github import GitHubClient
from flow.comment_writer import build_plan_board_comment
from flow.human_messages import (
    goal_complete_comment,
    planner_false_done_comment,
    task_cancelled_by_planner_comment,
)
from flow.manifest import (
    GoalBody,
    ManifestEntry,
    TaskBody,
    TaskSpec,
    render_task_prose,
)
from flow.metrics import EVENTS, emit
from flow.state_machine import TERMINAL_STATES


@dataclass
class CurrentChild:
    issue: object  # PyGithub Issue
    task_id: str
    state_label: str
    body: TaskBody


def _state_of(labels: list[str]) -> str | None:
    from flow.state_machine import EXTERNAL_STATES

    for n in labels:
        if n in EXTERNAL_STATES:
            return n
    return None


def _upsert_plan_board(
    *,
    client: GitHubClient,
    goal_issue,
    goal_body: GoalBody,
    planner_result,
    current_children: list[CurrentChild],
) -> None:
    """Create or update the goal-issue plan/progress comment."""
    children_progress = []
    by_task = {c.task_id: c for c in current_children}
    for entry in goal_body.manifest:
        c = by_task.get(entry.task_id)
        if c is not None:
            title = c.body.spec.goal if c.body and c.body.spec else c.issue.title
            state = c.state_label
        else:
            title = ""
            state = entry.state
        children_progress.append({
            "task_id": entry.task_id,
            "issue": entry.issue,
            "state": state,
            "title": title,
            "deps": list(entry.deps or []),
        })

    summary = ""
    if planner_result.status == "done":
        summary = planner_result.summary or "Goal complete."
    elif planner_result.status == "blocked":
        blk = planner_result.blocker or {}
        summary = f"⚠️ Planner 阻塞：{blk.get('question', '需要人类决策')}"

    body = build_plan_board_comment(
        iteration=goal_body.agent_state.planner_iteration,
        last_run=goal_body.agent_state.last_planner_run,
        status=planner_result.status,
        summary=summary,
        desired_plan=list(planner_result.desired_plan or []),
        children_progress=children_progress,
    )

    try:
        comment = client.upsert_comment(
            goal_issue, goal_body.agent_state.plan_comment_id, body
        )
        if comment is not None:
            goal_body.agent_state.plan_comment_id = int(getattr(comment, "id", 0)) or None
    except Exception as exc:
        print(f"[reconciler] plan-board upsert failed: {exc}", flush=True)


def reconcile(
    *,
    planner_result,
    repo,
    goal_issue,
    goal_body: GoalBody,
    current_children: list[CurrentChild],
    client: GitHubClient,
    base_branch: str = "main",
) -> None:
    """Apply Planner result to the goal tree (spec §5.5)."""
    if planner_result.status == "blocked":
        from flow.comment_writer import build_needs_human_comment

        blocker = planner_result.blocker or {}
        comment = build_needs_human_comment(
            prose=f"Planner 阻塞：{blocker.get('question', '需要人类决策')}",
            agent_state=blocker.get("agent_state",
                                    {"stage": "planner", "blocker_type": "unknown"}),
            decision={
                "question": blocker.get("question", "请人工决策"),
                "options": blocker.get("options", []),
                "custom_allowed": blocker.get("custom_allowed", True),
            },
        )
        client.comment(goal_issue, comment)
        client.set_state_label(goal_issue, "needs-human")
        _upsert_plan_board(
            client=client, goal_issue=goal_issue, goal_body=goal_body,
            planner_result=planner_result, current_children=current_children,
        )
        client.update_issue_body(goal_issue, goal_body.to_body())
        emit(EVENTS.PLANNER_BLOCKED, issue_iid=goal_issue.number)
        return

    if planner_result.status == "done":
        # Hard guard: refuse done if any child is non-terminal (spec §5.7)
        non_terminal = [c for c in current_children if c.state_label not in TERMINAL_STATES]
        if non_terminal:
            emit(EVENTS.PLANNER_FALSE_DONE, issue_iid=goal_issue.number,
                 non_terminal=[c.issue.number for c in non_terminal])
            client.comment(
                goal_issue,
                planner_false_done_comment(
                    non_terminal_issues=[c.issue.number for c in non_terminal],
                ),
            )
            client.set_state_label(goal_issue, "needs-human")
            return
        client.comment(goal_issue,
                       goal_complete_comment(summary=planner_result.summary))
        client.set_state_label(goal_issue, "agent-done")
        _upsert_plan_board(
            client=client, goal_issue=goal_issue, goal_body=goal_body,
            planner_result=planner_result, current_children=current_children,
        )
        client.update_issue_body(goal_issue, goal_body.to_body())
        client.close_issue(goal_issue)
        emit(EVENTS.GOAL_DONE, issue_iid=goal_issue.number)
        return

    # status == "ok": apply desired_plan as set operations
    desired = {t.get("task_id"): t for t in planner_result.desired_plan if t.get("task_id")}
    observed = {c.task_id: c for c in current_children if c.task_id}

    # 1) Create new tasks
    for task_id, t in desired.items():
        if task_id in observed:
            continue
        spec_dict = t.get("spec") or {}
        deps = list(t.get("deps") or [])
        parent_task_id = t.get("parent_task_id")

        body = TaskBody(
            task_id=task_id,
            goal_issue=goal_issue.number,
            parent_task_id=parent_task_id,
            spec=TaskSpec.from_dict(spec_dict),
            deps=deps,
        )
        body.prose = render_task_prose(
            task_id=task_id,
            goal_issue=goal_issue.number,
            spec=body.spec,
            deps=deps,
        )
        title = f"[{task_id}] {body.spec.goal[:80] or 'task'}"
        # Choose initial state: agent-ready if no unmet deps, else stay agent-ready
        # but tag deps; Coordinator dispatch checks deps before launching.
        new_issue = client.create_issue(
            repo,
            title=title,
            body=body.to_body(),
            labels=["type:task", "agent-ready"],
        )
        goal_body.manifest.append(
            ManifestEntry(
                task_id=task_id,
                issue=new_issue.number,
                deps=deps,
                state="agent-ready",
                parent_task_id=parent_task_id,
            )
        )
        print(f"[reconciler] created task #{new_issue.number} {task_id}", flush=True)

    # 2) Update existing tasks' specs if drifted
    for task_id, t in desired.items():
        if task_id not in observed:
            continue
        child = observed[task_id]
        new_spec = TaskSpec.from_dict(t.get("spec") or {})
        if child.body.spec.to_dict() != new_spec.to_dict():
            child.body.spec = new_spec
            child.body.deps = list(t.get("deps") or [])
            child.body.prose = render_task_prose(
                task_id=task_id,
                goal_issue=goal_issue.number,
                spec=new_spec,
                deps=child.body.deps,
            )
            client.update_issue_body(child.issue, child.body.to_body())
            print(f"[reconciler] updated spec for {task_id} #{child.issue.number}", flush=True)

    # 3) Cancel tasks not in desired
    for task_id, child in observed.items():
        if task_id in desired:
            continue
        if child.state_label in TERMINAL_STATES:
            continue
        client.comment(child.issue, task_cancelled_by_planner_comment())
        client.set_state_label(child.issue, "agent-failed")
        # Mirror in manifest
        entry = goal_body.find_by_task_id(task_id)
        if entry:
            entry.state = "agent-failed"
        print(f"[reconciler] cancelled task {task_id} #{child.issue.number}", flush=True)

    # 4) Explicit actions
    actions = planner_result.actions or {}
    for patch in actions.get("modify_specs", []) or []:
        tid = patch.get("task_id")
        target = next((c for c in current_children if c.task_id == tid), None)
        if not target:
            continue
        spec_patch = patch.get("patch") or {}
        body = target.body
        for k, v in spec_patch.items():
            if hasattr(body.spec, k):
                setattr(body.spec, k, v)
        if patch.get("reset_review_iteration"):
            body.review.iteration = 0
        client.update_issue_body(target.issue, body.to_body())
        print(f"[reconciler] modify_specs applied to {tid}", flush=True)

    for cancel_id in actions.get("cancel_tasks", []) or []:
        target = next((c for c in current_children if c.task_id == cancel_id), None)
        if target and target.state_label not in TERMINAL_STATES:
            client.comment(target.issue, task_cancelled_by_planner_comment(
                reason="Planner 通过 `actions.cancel_tasks` 显式取消了该任务。"
            ))
            client.set_state_label(target.issue, "agent-failed")

    # 5) Sync manifest states from observed labels (truth source: labels)
    for entry in goal_body.manifest:
        # Try to find current label by issue number from observed
        match = next((c for c in current_children if c.task_id == entry.task_id), None)
        if match:
            entry.state = match.state_label

    # 6) Bump metadata
    goal_body.agent_state.planner_iteration += 1
    from datetime import datetime, timezone
    goal_body.agent_state.last_planner_run = datetime.now(timezone.utc).isoformat()
    goal_body.agent_state.dispatch_lock = None  # release; Coordinator owns this in §9

    client.update_issue_body(goal_issue, goal_body.to_body())

    _upsert_plan_board(
        client=client, goal_issue=goal_issue, goal_body=goal_body,
        planner_result=planner_result, current_children=current_children,
    )
    # Persist the (possibly newly-stored) plan_comment_id back into the body.
    client.update_issue_body(goal_issue, goal_body.to_body())

    emit(EVENTS.PLANNER_RECONCILED, issue_iid=goal_issue.number,
         desired=len(desired), observed=len(observed))


def gather_current_children(repo, goal_body: GoalBody) -> list[CurrentChild]:
    """Read each task Issue listed in manifest; tolerate missing issues."""
    out: list[CurrentChild] = []
    for entry in goal_body.manifest:
        try:
            issue = repo.get_issue(entry.issue)
        except Exception:
            continue
        labels = [lbl.name for lbl in issue.labels]
        state = _state_of(labels) or entry.state
        body = TaskBody.parse(issue.body or "")
        out.append(CurrentChild(issue=issue, task_id=entry.task_id,
                                state_label=state, body=body))
    return out
