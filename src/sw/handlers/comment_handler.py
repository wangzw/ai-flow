from typing import Callable

from sw.coder import run_coder
from sw.comment_parser import extract_agent_command
from sw.comment_writer import build_needs_human_comment
from sw.metrics import EVENTS, emit
from sw.state_machine import STATES, next_state_for_event


def _current_state_label(labels: list[str]) -> str | None:
    for lbl in labels:
        if lbl in STATES:
            return lbl
    return None


def handle_comment_event(
    *,
    project,
    issue_iid: int,
    comment_body: str,
    client,
    coder: Callable | None = None,
) -> None:
    cmd = extract_agent_command(comment_body)
    if cmd is None:
        return

    emit(EVENTS.COMMAND_RECEIVED, issue_iid=issue_iid, command=cmd)

    issue = project.issues.get(issue_iid)
    current = _current_state_label(issue.labels)
    next_label = next_state_for_event(current, f"command:{cmd}")
    if next_label is None:
        # Invalid command for current state — silently no-op.
        # (Real implementation may post a clarifying comment.)
        return

    client.set_state_label(issue, next_label)

    # Side-effect: resume and retry re-dispatch the coder.
    if cmd in ("resume", "retry"):
        coder = coder or (lambda **kw: run_coder(**kw))
        emit(EVENTS.CODER_DISPATCHED, issue_iid=issue_iid)
        coder_result = coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
        if coder_result is None or coder_result.success:
            return
        blocker = coder_result.blocker or {}
        emit(
            EVENTS.CODER_BLOCKER,
            issue_iid=issue_iid,
            blocker_type=blocker.get("blocker_type", "unknown"),
        )
        comment = build_needs_human_comment(
            prose=f"Coder 再次阻塞：{blocker.get('blocker_type', 'unknown')}",
            agent_state={
                "stage": "coder",
                "blocker_type": blocker.get("blocker_type", "unknown"),
            },
            decision={
                "question": blocker.get("question", "请人工决策"),
                "options": blocker.get("options", []),
                "custom_allowed": True,
            },
        )
        client.comment_on_issue(issue, comment)
        client.set_state_label(issue, "needs-human")
