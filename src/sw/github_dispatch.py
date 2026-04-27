"""GitHub Actions dispatch entry point.

Translates GitHub event env vars into calls against the framework's
handler/queue logic. This module is the GitHub mirror of GitLab's
`webhook_relay.py` + handler invocations.

Usage (invoked from .github/workflows/*.yml):
    python -m sw.github_dispatch <command>

Commands:
    issue-labeled    — handle Issue label event (SW_ISSUE_NUMBER, SW_LABEL_ADDED)
    comment-created  — handle Issue comment (SW_ISSUE_NUMBER, SW_COMMENT_BODY)
    pr-ready         — handle PR ready_for_review (SW_PR_NUMBER)
    merge-queue      — process the merge queue (no per-PR env)

NOTE (scope): This dispatcher establishes the GitHub event ingress and
delegates to platform-portable logic (state_machine, comment_parser,
ac_validator, comment_writer). The current GitLab-flavored handlers
(`sw.handlers.*`) and `sw.coder` / `sw.merge_queue` use python-gitlab
idioms. A future plan will refactor those modules to accept an abstract
client so this dispatcher can drive them directly. Until then, this
module performs the platform-agnostic decisions inline (AC validation,
state-label transitions, comment generation) and uses GitHubClient for
API I/O.
"""

import os
import sys

from sw.ac_validator import validate_ac
from sw.comment_parser import extract_agent_command
from sw.comment_writer import build_needs_human_comment
from sw.github_client import GitHubClient
from sw.state_machine import STATES, next_state_for_event


def _client() -> GitHubClient:
    token = os.environ["GITHUB_TOKEN"]
    return GitHubClient.from_env(token=token)


def _repo(client: GitHubClient):
    return client.get_repo(os.environ["SW_REPO"])


def _current_state_label(label_names: list[str]) -> str | None:
    for name in label_names:
        if name in STATES:
            return name
    return None


def _label_names(issue) -> list[str]:
    return [lbl.name for lbl in issue.labels]


def cmd_issue_labeled() -> int:
    """Handle issues.labeled event. Mirrors sw.handlers.issue_handler.handle_issue_event."""
    label = os.environ.get("SW_LABEL_ADDED")
    if label != "agent-ready":
        return 0

    client = _client()
    repo = _repo(client)
    issue = repo.get_issue(int(os.environ["SW_ISSUE_NUMBER"]))

    result = validate_ac(issue.body or "")
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
        return 0

    client.set_state_label(issue, "agent-working")
    # Real Coder dispatch is platform-specific (uses copilot CLI + PyGithub idioms).
    # See coder.py for the Claude Code/GitLab analog. Future plan will provide coder_gh.py.
    print(f"[github] dispatched coder for issue #{issue.number} (placeholder)")
    return 0


def cmd_comment_created() -> int:
    """Handle issue_comment.created event."""
    body = os.environ.get("SW_COMMENT_BODY", "")
    cmd = extract_agent_command(body)
    if cmd is None:
        return 0

    client = _client()
    repo = _repo(client)
    issue = repo.get_issue(int(os.environ["SW_ISSUE_NUMBER"]))

    current = _current_state_label(_label_names(issue))
    next_label = next_state_for_event(current, f"command:{cmd}")
    if next_label is None:
        return 0

    client.set_state_label(issue, next_label)
    if cmd in ("resume", "retry"):
        print(f"[github] dispatched coder for issue #{issue.number} (resume/retry placeholder)")
    return 0


def cmd_pr_ready() -> int:
    """Handle pull_request.ready_for_review event. Future: invoke reviewer matrix."""
    pr_number = int(os.environ["SW_PR_NUMBER"])
    print(f"[github] pr ready #{pr_number} — reviewer matrix dispatch placeholder")
    # Future: clone + run sw.reviewer.run_review_matrix; on all-pass add `merge-queued` label.
    return 0


def cmd_merge_queue() -> int:
    """Process the merge queue. Future: invoke process_merge_queue with GitHub adapter."""
    print("[github] merge queue placeholder")
    return 0


_COMMANDS = {
    "issue-labeled": cmd_issue_labeled,
    "comment-created": cmd_comment_created,
    "pr-ready": cmd_pr_ready,
    "merge-queue": cmd_merge_queue,
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in _COMMANDS:
        print(f"usage: python -m sw.github_dispatch <{'|'.join(_COMMANDS)}>", file=sys.stderr)
        return 2
    return _COMMANDS[args[0]]()


if __name__ == "__main__":
    sys.exit(main())
