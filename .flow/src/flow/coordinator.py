"""Coordinator dispatch entry — equivalent of sw.github_dispatch.

Translates GitHub Actions events into handler calls.

Usage (from .github/workflows/flow-*.yml):
    python -m flow.coordinator <command>

Commands:
    issue-labeled   — SW_ISSUE_NUMBER, SW_LABEL_ADDED
    comment-created — SW_ISSUE_NUMBER, SW_COMMENT_BODY, SW_COMMENT_AUTHOR
    pr-ready        — SW_PR_NUMBER
    merge-queue     — (no per-PR env)
    schedule        — cron sweep
"""

from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


def cmd_issue_labeled() -> int:
    from flow.handlers.issue_handler import handle_issue_labeled

    return handle_issue_labeled()


def cmd_comment_created() -> int:
    from flow.handlers.comment_handler import handle_comment_created

    return handle_comment_created()


def cmd_pr_ready() -> int:
    from flow.handlers.pr_handler import handle_pr_ready

    return handle_pr_ready()


def cmd_merge_queue() -> int:
    from flow.clients.github import GitHubClient
    from flow.merge_queue import process_merge_queue

    gh = GitHubClient.from_token(os.environ["GITHUB_TOKEN"])
    repo = gh.get_repo(os.environ["SW_REPO"])
    n = process_merge_queue(repo=repo, client=gh)
    print(f"[dispatch] merge_queue processed {n}", flush=True)
    return 0


def cmd_schedule() -> int:
    from flow.handlers.schedule_handler import handle_schedule

    return handle_schedule()


_COMMANDS = {
    "issue-labeled": cmd_issue_labeled,
    "comment-created": cmd_comment_created,
    "pr-ready": cmd_pr_ready,
    "merge-queue": cmd_merge_queue,
    "schedule": cmd_schedule,
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in _COMMANDS:
        print(f"usage: python -m flow.coordinator <{'|'.join(_COMMANDS)}>", file=sys.stderr)
        return 2
    return _COMMANDS[args[0]]()


if __name__ == "__main__":
    sys.exit(main())
