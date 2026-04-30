"""Issue comment slash command handler (spec §10).

Supports: start / resume / retry / abort / escalate / decide <id> / replan [hint].
"""

from __future__ import annotations

import os

from flow.clients.github import GitHubClient
from flow.comment_parser import extract_agent_command, is_authorized
from flow.comment_writer import build_ack_comment
from flow.config import Config
from flow.manifest import GoalBody, TaskBody
from flow.metrics import EVENTS, emit
from flow.state_machine import STATES, next_state_for_event


def _current_state(issue) -> str | None:
    for lbl in issue.labels:
        if lbl.name in STATES:
            return lbl.name
    return None


def _is_goal(issue) -> bool:
    return any(lbl.name == "type:goal" for lbl in issue.labels)


def _cascade_goal_abort(*, goal_issue, repo, gh) -> tuple[list[int], list[int]]:
    """Cascade /agent abort from a Goal to its children: cancel all
    non-terminal task issues and close their open PRs.

    Returns (cancelled_task_issue_numbers, closed_pr_numbers).
    """
    from flow.human_messages import goal_aborted_cascade_comment

    gb = GoalBody.parse(goal_issue.body or "")
    cancelled: list[int] = []
    closed_prs: list[int] = []
    for entry in gb.manifest:
        try:
            task_issue = repo.get_issue(entry.issue)
        except Exception:
            continue
        cur = _current_state(task_issue)
        if cur in ("agent-done", "agent-failed"):
            continue
        # Close associated PRs first (so the cascade comment can mention them).
        pr_nums: list[int] = []
        try:
            tb = TaskBody.parse(task_issue.body or "")
            for art in tb.artifacts or []:
                if not isinstance(art, dict):
                    continue
                pr_num = art.get("pr")
                if pr_num is None:
                    continue
                try:
                    pr = repo.get_pull(int(pr_num))
                    if pr.state == "open":
                        pr.edit(state="closed")
                        pr_nums.append(int(pr_num))
                except Exception as exc:
                    print(f"[cascade] close PR #{pr_num} failed: {exc}", flush=True)
        except Exception:
            pass
        closed_prs.extend(pr_nums)
        try:
            gh.comment(task_issue, goal_aborted_cascade_comment(
                goal=goal_issue.number, closed_prs=pr_nums or None,
            ))
        except Exception:
            pass
        try:
            gh.set_state_label(task_issue, "agent-failed")
        except Exception:
            pass
        try:
            if task_issue.state != "closed":
                task_issue.edit(state="closed")
        except Exception as exc:
            print(f"[cascade] close task #{entry.issue} failed: {exc}", flush=True)
        cancelled.append(entry.issue)
    return cancelled, closed_prs


def _close_task_open_prs(*, task_issue, repo) -> list[int]:
    """For /agent abort on a task: close any open PRs listed in the task's
    artifacts. Returns list of closed PR numbers."""
    closed: list[int] = []
    try:
        tb = TaskBody.parse(task_issue.body or "")
    except Exception:
        return closed
    for art in tb.artifacts or []:
        if not isinstance(art, dict):
            continue
        pr_num = art.get("pr")
        if pr_num is None:
            continue
        try:
            pr = repo.get_pull(int(pr_num))
            if pr.state == "open":
                pr.edit(state="closed")
                closed.append(int(pr_num))
        except Exception as exc:
            print(f"[task-abort] close PR #{pr_num} failed: {exc}", flush=True)
    return closed


def handle_comment_created() -> int:
    body = os.environ.get("FLOW_COMMENT_BODY", "")
    cmd = extract_agent_command(body)
    if cmd is None:
        return 0

    cfg = Config.load()
    actor = os.environ.get("FLOW_COMMENT_AUTHOR")
    if not is_authorized(actor, cfg.authorized_users):
        print(f"[comment] {actor!r} not authorized; ignoring /agent {cmd.name}",
              flush=True)
        # Silently ignore (no ack) per spec §10.4 fail-closed default
        return 0

    emit(EVENTS.COMMAND_RECEIVED, command=cmd.name, actor=actor)

    gh = GitHubClient.from_env()
    repo = gh.get_repo(os.environ["FLOW_REPO"])
    issue = repo.get_issue(int(os.environ["FLOW_ISSUE_NUMBER"]))

    current = _current_state(issue)
    next_label = next_state_for_event(current, f"command:{cmd.name}")
    if next_label is None:
        gh.comment(
            issue,
            build_ack_comment(
                command=cmd.name,
                accepted=False,
                reason=(
                    f"当前状态 `{current}` 不接受 `/agent {cmd.name}`。"
                    f"请检查 issue 的状态标签，或先用其它命令切换状态。"
                ),
            ),
        )
        return 0

    # Acknowledge receipt FIRST — before any body mutations, label changes,
    # or dispatching the (potentially slow) planner/implementer subprocess.
    # This guarantees the human sees immediate feedback that their command
    # was received, even if downstream work later fails or stalls.
    #
    # Use a 👍 reaction on the user's comment (lightweight, non-spammy)
    # rather than posting a reply comment. Falls back to a comment if the
    # reaction API call fails or the comment id wasn't provided.
    comment_id_raw = os.environ.get("FLOW_COMMENT_ID", "").strip()
    reacted = False
    if comment_id_raw:
        try:
            reacted = gh.react_to_comment(
                issue, int(comment_id_raw), reaction="+1",
            )
        except ValueError:
            reacted = False
    if not reacted:
        gh.comment(issue, build_ack_comment(command=cmd.name, accepted=True))

    # decide: write decision_response into body, then transition + restart
    if cmd.name == "decide" and cmd.arg:
        if _is_goal(issue):
            gb = GoalBody.parse(issue.body or "")
            gb.agent_state.dispatch_lock = None
            # Re-trigger Planner with replan_hint = chosen option
            gh.update_issue_body(issue, gb.to_body())
        else:
            tb = TaskBody.parse(issue.body or "")
            tb.agent_state.decision_response = cmd.arg
            tb.agent_state.stage = "implementer"
            gh.update_issue_body(issue, tb.to_body())

    if cmd.name == "replan" and _is_goal(issue):
        gb = GoalBody.parse(issue.body or "")
        gb.agent_state.last_planner_run = None
        # Clear any in-flight dispatch lock so the planner re-runs even if
        # /agent replan was issued mid-flight (state == agent-working).
        gb.agent_state.dispatch_lock = None
        gh.update_issue_body(issue, gb.to_body())

    # /agent abort: cascade so children & PRs don't dangle in non-terminal
    # states after the goal/task is declared failed.
    if cmd.name == "abort":
        from flow.human_messages import (
            goal_abort_summary_comment,
            task_aborted_pr_closed_comment,
        )

        if _is_goal(issue):
            cancelled, closed_prs = _cascade_goal_abort(
                goal_issue=issue, repo=repo, gh=gh,
            )
            try:
                gh.comment(
                    issue,
                    goal_abort_summary_comment(
                        cancelled_tasks=cancelled, closed_prs=closed_prs,
                    ),
                )
            except Exception:
                pass
            # Close the goal issue itself once children are cleaned up.
            try:
                if issue.state != "closed":
                    issue.edit(state="closed")
            except Exception as exc:
                print(f"[abort] close goal #{issue.number} failed: {exc}",
                      flush=True)
        else:
            closed_prs = _close_task_open_prs(task_issue=issue, repo=repo)
            for pr_num in closed_prs:
                try:
                    gh.comment(issue, task_aborted_pr_closed_comment(pr=pr_num))
                except Exception:
                    pass
            try:
                if issue.state != "closed":
                    issue.edit(state="closed")
            except Exception as exc:
                print(f"[abort] close task #{issue.number} failed: {exc}",
                      flush=True)

    gh.set_state_label(issue, next_label)

    # If transitioning to a state that should re-dispatch, route to issue_handler.
    if next_label in ("agent-ready", "agent-working"):
        # Simulate label-added event
        os.environ["FLOW_LABEL_ADDED"] = "agent-ready"
        from flow.handlers.issue_handler import handle_issue_labeled

        # Set label so handler picks correct branch (already set above for ready)
        if next_label == "agent-working":
            # For replan/decide we already set agent-working; force re-dispatch
            os.environ["FLOW_LABEL_ADDED"] = "agent-ready"
        return handle_issue_labeled()
    return 0
