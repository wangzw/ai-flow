"""Real Coder Agent for GitHub: orchestrates Copilot CLI to implement an Issue's AC.

Mirror of `sw.coder.run_coder` but using PyGithub repo and Copilot CLI.
Returns the same CoderResult dataclass.
"""

import os
import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from sw.copilot_cli_client import CopilotCliClient


@dataclass(frozen=True)
class CoderResult:
    success: bool
    mr_iid: int | None = None  # pr.number for GitHub
    branch_name: str = ""
    blocker: dict | None = None


_PROMPT_TEMPLATE = """You are an autonomous coding agent implementing an Issue's AC.

Project root: {cwd}
Issue title: {title}
Issue body:
---
{body}
---

Your task:
1. Read the AC block in the Issue body (between <!-- ac:start --> and <!-- ac:end -->).
2. Implement the requested change in this project. Follow existing patterns and conventions.
3. Write tests covering each AC item before implementation (TDD).
4. For any non-obvious WHY (constraints, workarounds, invariants), add a code comment —
   this is the only channel reviewers will see your reasoning.
   Commit messages will NOT be read by reviewers.
5. Iterate until all tests pass locally.
6. Stage all changes and commit them with a clear message.

When done — and ONLY when all tests pass and code is committed — write a result marker:

  mkdir -p .agent
  cat > .agent/result.yaml <<'EOF'
  status: done
  summary: <one-line summary of what you did>
  EOF

If you cannot proceed (AC ambiguous, conflict requires human decision, missing context):

  mkdir -p .agent
  cat > .agent/result.yaml <<'EOF'
  status: blocked
  blocker_type: <ac_ambiguity | conflict | needs_choice | other>
  question: <human-readable question>
  options:
    - id: <id>
      desc: <description>
  EOF

Then exit. Do NOT proceed past blocked.
"""


def _clone_repo(url: str, to_path: Path, branch: str | None = None):
    from git import Repo

    if branch:
        return Repo.clone_from(url, to_path, branch=branch)
    return Repo.clone_from(url, to_path)


def _push_branch(repo, branch_name: str):
    repo.git.push("--set-upstream", "origin", branch_name)


def _read_result(workdir: Path) -> dict | None:
    marker = workdir / ".agent" / "result.yaml"
    if not marker.exists():
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(marker.read_text()))
    except Exception:
        return None


def run_coder_gh(
    *,
    repo,
    issue_number: int,
    issue_title: str,
    cli: CopilotCliClient | None = None,
    workdir: Path | None = None,
) -> CoderResult:
    """Run real Coder for GitHub: clone, prompt Copilot CLI, parse result, push & open PR."""
    cli = cli or CopilotCliClient()
    workdir = workdir or Path(tempfile.mkdtemp(prefix=f"agent-issue-{issue_number}-"))
    branch_name = f"agent/issue-{issue_number}"
    base = repo.default_branch

    issue = repo.get_issue(issue_number)
    body = issue.body or ""

    repo_path = workdir / "repo"
    # URL selection:
    # - SW_GIT_TOKEN env (set in CI): build HTTPS URL with embedded token for clone+push
    # - Else: use SSH URL (local users typically have SSH keys configured)
    sw_git_token = os.environ.get("SW_GIT_TOKEN")
    if sw_git_token:
        https = repo.clone_url
        prefix = "https://"
        clone_url = https.replace(prefix, f"{prefix}x-access-token:{sw_git_token}@", 1)
    else:
        clone_url = getattr(repo, "ssh_url", None) or repo.clone_url
    try:
        local_repo = _clone_repo(clone_url, repo_path, branch=base)
    except Exception as exc:
        return CoderResult(
            success=False,
            blocker={"blocker_type": "clone_failed", "reason": str(exc)},
            branch_name=branch_name,
        )

    try:
        local_repo.git.checkout("-b", branch_name)
    except Exception:
        pass

    prompt = _PROMPT_TEMPLATE.format(cwd=str(repo_path), title=issue_title, body=body)

    cli_result = cli.run(prompt=prompt, cwd=repo_path)

    # Marker file is the canonical signal. Trust it even if CLI exited non-zero
    # (some CLIs return non-zero for benign post-task reasons after completing work).
    marker = _read_result(repo_path)
    if marker is None:
        if cli_result.returncode != 0:
            return CoderResult(
                success=False,
                blocker={
                    "blocker_type": "subprocess_error",
                    "returncode": cli_result.returncode,
                    "stdout": (cli_result.stdout or "")[-2000:],
                    "stderr": (cli_result.stderr or "")[-2000:],
                    "cwd": str(repo_path),
                    "branch": branch_name,
                },
                branch_name=branch_name,
            )
        return CoderResult(
            success=False,
            blocker={
                "blocker_type": "no_result_marker",
                "returncode": cli_result.returncode,
                "stdout": (cli_result.stdout or "")[-2000:],
                "stderr": (cli_result.stderr or "")[-2000:],
                "cwd": str(repo_path),
                "branch": branch_name,
            },
            branch_name=branch_name,
        )

    if marker.get("status") == "blocked":
        return CoderResult(
            success=False,
            blocker={
                "blocker_type": marker.get("blocker_type", "unknown"),
                "question": marker.get("question", ""),
                "options": marker.get("options", []),
            },
            branch_name=branch_name,
        )

    if marker.get("status") != "done":
        return CoderResult(
            success=False,
            blocker={"blocker_type": "unknown_status", "raw": marker},
            branch_name=branch_name,
        )

    _push_branch(local_repo, branch_name)

    pr = repo.create_pull(
        title=f"Draft: {issue_title}",
        body=(
            f"Auto-generated by Coder Agent for issue #{issue_number}.\n\n"
            f"Closes #{issue_number}\n\n"
            f"Summary: {marker.get('summary', '')}"
        ),
        head=branch_name,
        base=base,
        draft=True,
    )

    return CoderResult(success=True, mr_iid=pr.number, branch_name=branch_name)
