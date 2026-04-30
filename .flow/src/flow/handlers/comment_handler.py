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
        gh.update_issue_body(issue, gb.to_body())

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
