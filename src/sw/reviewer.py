"""Real Reviewer Matrix: orchestrates Claude Code to audit an MR per spec §5.

Single-Agent sequential mode (spec §5.3 implementation a): for each MUST
dimension we invoke Claude Code with a dimension-specific prompt; each
invocation writes a marker `.review/<dim>.yaml`. Results aggregate into
ReviewResult.

Spec constraints:
- Reviewer reads AC + diff + tests + code comments only (NOT commit messages)
- Different system prompts per dimension provide cross-dimension heterogeneity
- Coder vs Reviewer heterogeneity via distinct role prompts
"""

from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from sw.claude_code_client import ClaudeCodeClient

MUST_DIMENSIONS = (
    "ac_compliance",
    "test_quality",
    "security",
    "performance",
    "consistency",
    "documentation_sync",
    "migration_safety",
)


@dataclass(frozen=True)
class ReviewResult:
    all_passed: bool
    dimension_results: dict[str, str]
    failed_dimensions: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)


_DIMENSION_PROMPTS = {
    "ac_compliance": (
        "You are an AC Compliance Reviewer. Read the Issue's AC block and the MR diff. "
        "Verify EVERY AC item is satisfied by the implementation + tests. "
        "Do NOT read commit messages — they are off-limits. "
        "Output PASS only if every AC item is verifiably implemented; otherwise FAIL with reason."
    ),
    "test_quality": (
        "You are a Test Quality Reviewer. Check that tests truly cover the AC, "
        "have non-empty assertions, are not tautologies, and have not been weakened to fit "
        "a buggy implementation. Output PASS or FAIL with reason."
    ),
    "security": (
        "You are a Security Reviewer. Audit the diff for OWASP top-10 risks: injection, "
        "auth issues, sensitive data exposure, etc. Apply standard secure-coding rules. "
        "Output PASS or FAIL with reason."
    ),
    "performance": (
        "You are a Performance Reviewer. Compare the diff against any performance baseline "
        "in the project. If no baseline exists, output PASS with reason 'no baseline'. "
        "Otherwise output PASS or FAIL with concrete metric."
    ),
    "consistency": (
        "You are a Consistency Reviewer. Verify the diff follows existing project conventions: "
        "lint clean, naming, style, and cross-file structure. Output PASS or FAIL with reason."
    ),
    "documentation_sync": (
        "You are a Documentation Sync Reviewer. Check that API spec / user docs / README / "
        "comments are consistent with the implementation. Output PASS or FAIL with reason."
    ),
    "migration_safety": (
        "You are a Migration Safety Reviewer. If the diff contains no DB schema or data "
        "migration changes, output PASS with reason 'no migration'. Otherwise verify the "
        "migration is safe under concurrent writes and reversible. Output PASS or FAIL."
    ),
}

_PROMPT_ENVELOPE = """{role}

Project root: {cwd}

Your task — review dimension: **{dim}**

Read:
- The AC block in the original Issue (if present in the project context)
- The diff at HEAD vs the base branch (run: git diff <base>..HEAD)
- The test files added/modified
- Any code comments in the modified files

Do NOT read git commit messages. They are explicitly off-limits per spec.

When finished, write a marker file:

  mkdir -p .review
  cat > .review/{dim}.yaml <<'EOF'
  result: PASS    # or FAIL
  reason: <one-line reason>
  EOF

Then exit.
"""


def _read_marker(repo_path: Path, dim: str) -> dict | None:
    marker = repo_path / ".review" / f"{dim}.yaml"
    if not marker.exists():
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(marker.read_text()))
    except Exception:
        return None


def _review_one(
    *, dim: str, claude: ClaudeCodeClient, repo_path: Path
) -> tuple[str, str]:
    """Run review for one dimension. Returns (status, reason)."""
    role = _DIMENSION_PROMPTS[dim]
    prompt = _PROMPT_ENVELOPE.format(role=role, cwd=str(repo_path), dim=dim)

    cc_result = claude.run(prompt=prompt, cwd=repo_path)
    if cc_result.returncode != 0:
        return "FAIL", f"subprocess error (rc={cc_result.returncode})"

    marker = _read_marker(repo_path, dim)
    if marker is None:
        return "FAIL", "no marker produced"

    status = str(marker.get("result", "FAIL")).upper()
    if status not in ("PASS", "FAIL"):
        return "FAIL", f"invalid marker result: {status!r}"
    return status, str(marker.get("reason", ""))


def run_review_matrix(
    *,
    mr_iid: int,
    project_path: str,
    claude: ClaudeCodeClient | None = None,
    repo_path: Path | None = None,
) -> ReviewResult:
    """Run all MUST dimension reviews sequentially. Fail-closed on any error."""
    claude = claude or ClaudeCodeClient()
    if repo_path is None:
        raise ValueError("repo_path is required for real reviewer")

    dimension_results: dict[str, str] = {}
    reasons: dict[str, str] = {}
    failed: list[str] = []

    for dim in MUST_DIMENSIONS:
        status, reason = _review_one(dim=dim, claude=claude, repo_path=repo_path)
        dimension_results[dim] = status
        reasons[dim] = reason
        if status != "PASS":
            failed.append(dim)

    return ReviewResult(
        all_passed=not failed,
        dimension_results=dimension_results,
        failed_dimensions=failed,
        reasons=reasons,
    )
