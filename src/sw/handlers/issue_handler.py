from typing import Callable

from sw.ac_validator import validate_ac
from sw.coder_fake import run_coder
from sw.comment_writer import build_needs_human_comment


def handle_issue_event(
    *,
    project,
    issue_iid: int,
    action: str,
    label: str | None,
    client,
    coder: Callable | None = None,
) -> None:
    """Dispatch handler for issue events from GitLab CI.

    Currently handles only `action='label_added' && label='agent-ready'`.
    """
    if action != "label_added" or label != "agent-ready":
        return

    coder = coder or (lambda **kw: run_coder(**kw))

    issue = project.issues.get(issue_iid)
    result = validate_ac(issue.description or "")

    if not result.valid:
        comment = build_needs_human_comment(
            prose=f"AC 验收失败：{result.reason}。请补充 AC 后重新打 `agent-ready` 标签。",
            agent_state={"stage": "ac_validation", "blocker_type": "ac_invalid"},
            decision={
                "question": "如何修复 AC？",
                "options": [
                    {"id": "edit_issue", "desc": "编辑 Issue body 补充 AC，移除并重打 agent-ready"},
                ],
                "custom_allowed": True,
            },
        )
        client.comment_on_issue(issue, comment)
        client.set_state_label(issue, "needs-human")
        return

    client.set_state_label(issue, "agent-working")
    coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
