"""Real Coder Agent: orchestrates Claude Code to implement an Issue's AC."""

import tempfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from sw.claude_code_client import ClaudeCodeClient


@dataclass(frozen=True)
class CoderResult:
    success: bool
    mr_iid: int | None = None
    branch_name: str = ""
    blocker: dict | None = None  # populated when success=False


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
    """Wrapper around git clone to allow patching in tests."""
    from git import Repo

    if branch:
        return Repo.clone_from(url, to_path, branch=branch)
    return Repo.clone_from(url, to_path)


def _push_branch(repo, branch_name: str):
    """Push the agent branch upstream. Patchable in tests."""
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


def run_coder(
    *,
    project,
    issue_iid: int,
    issue_title: str,
    claude: ClaudeCodeClient | None = None,
    workdir: Path | None = None,
) -> CoderResult:
    """Run real Coder: clone, prompt Claude Code, parse result, push & open MR.

    `claude` and `workdir` are injectable for testing.
    """
    claude = claude or ClaudeCodeClient()
    workdir = workdir or Path(tempfile.mkdtemp(prefix=f"agent-issue-{issue_iid}-"))
    branch_name = f"agent/issue-{issue_iid}"
    base = project.default_branch

    issue = project.issues.get(issue_iid)
    body = issue.description or ""

    repo_path = workdir / "repo"
    try:
        repo = _clone_repo(project.http_url_to_repo, repo_path, branch=base)
    except Exception as exc:
        return CoderResult(
            success=False,
            blocker={"blocker_type": "clone_failed", "reason": str(exc)},
            branch_name=branch_name,
        )

    # New branch for the agent's work
    try:
        repo.git.checkout("-b", branch_name)
    except Exception:
        pass  # may already exist; ignore

    prompt = _PROMPT_TEMPLATE.format(cwd=str(repo_path), title=issue_title, body=body)

    cc_result = claude.run(prompt=prompt, cwd=repo_path)

    # Marker file is the canonical signal. Trust it even if CLI exited non-zero
    # (some CLIs return non-zero for benign post-task reasons after completing work).
    marker = _read_result(repo_path)
    if marker is None:
        if cc_result.returncode != 0:
            return CoderResult(
                success=False,
                blocker={
                    "blocker_type": "subprocess_error",
                    "returncode": cc_result.returncode,
                    "stdout": (cc_result.stdout or "")[-2000:],
                    "stderr": (cc_result.stderr or "")[-2000:],
                    "cwd": str(repo_path),
                    "branch": branch_name,
                },
                branch_name=branch_name,
            )
        return CoderResult(
            success=False,
            blocker={
                "blocker_type": "no_result_marker",
                "returncode": cc_result.returncode,
                "stdout": (cc_result.stdout or "")[-2000:],
                "stderr": (cc_result.stderr or "")[-2000:],
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

    # Done — push & open MR
    _push_branch(repo, branch_name)

    mr = project.mergerequests.create(
        {
            "source_branch": branch_name,
            "target_branch": base,
            "title": f"Draft: {issue_title}",
            "description": (
                f"Auto-generated by Coder Agent for issue #{issue_iid}.\n\n"
                f"Closes #{issue_iid}\n\n"
                f"Summary: {marker.get('summary', '')}"
            ),
            "remove_source_branch": True,
        }
    )

    return CoderResult(success=True, mr_iid=mr.iid, branch_name=branch_name)
