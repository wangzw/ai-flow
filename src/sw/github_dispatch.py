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

Architecture: this dispatcher composes platform-agnostic logic
(state_machine, comment_parser, ac_validator, comment_writer) with
GitHub-specific implementations (coder_gh, merge_queue_gh, github_client,
copilot_cli_client) and the platform-agnostic reviewer (which accepts any
CLI client with the .run() interface — here CopilotCliClient).

The original GitLab-flavored handlers (`sw.handlers.*`) and `sw.coder` /
`sw.merge_queue` are NOT used on this path — instead, we have parallel
`coder_gh` and `merge_queue_gh` modules. A future refactor could unify
these via a Protocol; for now, parity is via parallel implementations.
"""

import os
import sys
from pathlib import Path

from sw.ac_validator import validate_ac
from sw.coder_gh import run_coder_gh
from sw.comment_parser import extract_agent_command
from sw.comment_writer import build_needs_human_comment
from sw.copilot_cli_client import CopilotCliClient
from sw.github_client import GitHubClient
from sw.merge_queue_gh import process_merge_queue_gh
from sw.reviewer import run_review_matrix
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
    coder_result = run_coder_gh(repo=repo, issue_number=issue.number, issue_title=issue.title)
    if coder_result.success:
        return 0
    # Coder blocker → post needs-human comment, transition state
    client.comment_on_issue(issue, _format_blocker_comment(coder_result.blocker))
    client.set_state_label(issue, "needs-human")
    return 0


def _format_blocker_comment(blocker: dict | None) -> str:
    """Build a verbose, human-readable needs-human comment from a Coder blocker dict."""
    blocker = blocker or {}
    blocker_type = blocker.get("blocker_type", "unknown")
    prose_lines = [f"Coder 阻塞：**{blocker_type}**"]

    if "returncode" in blocker:
        prose_lines.append(f"\n- returncode: `{blocker['returncode']}`")
    if "branch" in blocker:
        prose_lines.append(f"- branch: `{blocker['branch']}`")
    if "cwd" in blocker:
        prose_lines.append(f"- cwd: `{blocker['cwd']}`")
    if "reason" in blocker:
        prose_lines.append(f"- reason: {blocker['reason']}")

    stdout = blocker.get("stdout") or ""
    stderr = blocker.get("stderr") or ""
    if stdout.strip():
        prose_lines.append(f"\n**stdout (last 2KB)**:\n```\n{stdout.strip()}\n```")
    if stderr.strip():
        prose_lines.append(f"\n**stderr (last 2KB)**:\n```\n{stderr.strip()}\n```")
    if not stdout.strip() and not stderr.strip() and "returncode" in blocker:
        prose_lines.append(
            "\n_(stdout 和 stderr 均为空 — CLI 静默退出非零，常见原因：认证失败/未配置)_"
        )

    return build_needs_human_comment(
        prose="\n".join(prose_lines),
        agent_state={"stage": "coder", "blocker_type": blocker_type},
        decision={
            "question": blocker.get("question", "请检查 stdout/stderr，修复后回复 /agent resume"),
            "options": blocker.get("options", []),
            "custom_allowed": True,
        },
    )


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
        coder_result = run_coder_gh(repo=repo, issue_number=issue.number, issue_title=issue.title)
        if coder_result.success:
            return 0
        client.comment_on_issue(issue, _format_blocker_comment(coder_result.blocker))
        client.set_state_label(issue, "needs-human")
    return 0


def cmd_pr_ready() -> int:
    """Handle pull_request.ready_for_review event: run reviewer matrix, enqueue if pass."""
    pr_number = int(os.environ["SW_PR_NUMBER"])
    client = _client()
    repo = _repo(client)
    pr = repo.get_pull(pr_number)

    # In GitHub Actions, the repo is already checked out by actions/checkout.
    # SW_REPO_PATH overrides the working directory; default to CWD.
    repo_path = Path(os.environ.get("SW_REPO_PATH", "."))

    cli = CopilotCliClient()
    result = run_review_matrix(
        mr_iid=pr_number,
        project_path=repo.full_name,
        claude=cli,
        repo_path=repo_path,
    )

    if result.all_passed:
        if not any(lbl.name == "merge-queued" for lbl in pr.labels):
            pr.add_to_labels("merge-queued")
        return 0
    # Fail: do not merge. Future enhancement could trigger Coder fix loop.
    return 0


def cmd_merge_queue() -> int:
    """Process the merge queue."""
    client = _client()
    repo = _repo(client)
    n = process_merge_queue_gh(repo=repo, client=client)
    print(f"[github] processed {n} PR(s) from merge queue")
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
