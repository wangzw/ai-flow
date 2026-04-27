"""Local smoke test for GitHub path.

Usage examples:

  GITHUB_TOKEN=ghp_xxx SW_REPO=owner/repo \\
      python scripts/smoke_local.py issue-labeled --issue 5 --label agent-ready

  GITHUB_TOKEN=ghp_xxx SW_REPO=owner/repo \\
      python scripts/smoke_local.py comment-created --issue 5 --comment '/agent resume'

  GITHUB_TOKEN=ghp_xxx SW_REPO=owner/repo \\
      python scripts/smoke_local.py pr-ready --pr 12

  GITHUB_TOKEN=ghp_xxx SW_REPO=owner/repo \\
      python scripts/smoke_local.py merge-queue

Sets the SW_* env vars expected by sw.github_dispatch and invokes it.
"""

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local smoke test for GitHub dispatch")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_issue = sub.add_parser("issue-labeled")
    p_issue.add_argument("--issue", type=int, required=True)
    p_issue.add_argument("--label", default="agent-ready")

    p_comment = sub.add_parser("comment-created")
    p_comment.add_argument("--issue", type=int, required=True)
    p_comment.add_argument("--comment", required=True)

    p_pr = sub.add_parser("pr-ready")
    p_pr.add_argument("--pr", type=int, required=True)

    p_mq = sub.add_parser("merge-queue")  # no extra args  # noqa: F841

    args = parser.parse_args(argv)

    if not os.environ.get("GITHUB_TOKEN"):
        print("error: GITHUB_TOKEN env var required", file=sys.stderr)
        return 2
    if not os.environ.get("SW_REPO"):
        print("error: SW_REPO env var required (e.g. owner/repo)", file=sys.stderr)
        return 2

    if args.cmd == "issue-labeled":
        os.environ["SW_ISSUE_NUMBER"] = str(args.issue)
        os.environ["SW_LABEL_ADDED"] = args.label
    elif args.cmd == "comment-created":
        os.environ["SW_ISSUE_NUMBER"] = str(args.issue)
        os.environ["SW_COMMENT_BODY"] = args.comment
    elif args.cmd == "pr-ready":
        os.environ["SW_PR_NUMBER"] = str(args.pr)

    from sw.github_dispatch import main as dispatch_main
    return dispatch_main([args.cmd])


if __name__ == "__main__":
    sys.exit(main())
