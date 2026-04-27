from typing import Callable

from sw.coder_stub import run_coder
from sw.comment_parser import extract_agent_command
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
        coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
