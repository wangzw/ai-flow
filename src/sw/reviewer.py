"""Real Reviewer Matrix: orchestrates Claude Code / Copilot CLI to audit an MR per spec §5.

Single-call combined mode (default, fast): one CLI invocation evaluates all 7
MUST dimensions sequentially within a single agent session. Output is one
marker `.review/combined.yaml` listing all results. ~5x faster than per-dim
calls because cold-start + codebase exploration happen once.

Per-dimension mode (legacy, kept for testing): one CLI invocation per dim,
each writes its own `.review/<dim>.yaml`. Slower (~35 min for 7 dims).

Mode selection: `run_review_matrix(combined=True)` is the default.

Spec constraints (apply to both modes):
- Reviewer reads AC + diff + tests + code comments only (NOT commit messages)
- Different roles per dimension via prompt sectioning
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


_COMBINED_PROMPT_TEMPLATE = """You are a senior code reviewer. Review the diff in this repo
against the 7 MUST dimensions below.

Project root: {cwd}
MR #: {mr_iid}

## What to read
- AC block in the linked Issue body (use `gh issue view <N>`; or check the PR
  description for `Closes #N`)
- The diff: `git diff origin/{base}..HEAD`
- All test files added/modified
- Code comments in modified files

## What NOT to read
Do NOT read git commit messages — they are explicitly off-limits per spec §5.3.

## Dimensions (evaluate each independently)

1. **ac_compliance** — Every AC item is implemented + has a test
2. **test_quality** — Tests have non-empty assertions, are not tautologies, were not weakened
3. **security** — OWASP top-10 risks (injection, auth, data exposure)
4. **performance** — Regression vs baseline; if no baseline, PASS with reason "no baseline"
5. **consistency** — Lint clean, naming/style/conventions follow project
6. **documentation_sync** — Docs/README/comments consistent with code
7. **migration_safety** — DB/data migration safe; if no migration, PASS with "no migration"

## Output

Write ONE marker file `.review/combined.yaml` with this exact structure:

  mkdir -p .review
  cat > .review/combined.yaml <<'EOF'
  results:
    ac_compliance: PASS    # or FAIL
    test_quality: PASS
    security: PASS
    performance: PASS
    consistency: PASS
    documentation_sync: PASS
    migration_safety: PASS
  reasons:
    ac_compliance: <one-line reason>
    test_quality: <one-line reason>
    security: <one-line reason>
    performance: <one-line reason>
    consistency: <one-line reason>
    documentation_sync: <one-line reason>
    migration_safety: <one-line reason>
  EOF

Then exit. Be efficient — read each file once; do not re-explore the codebase per dimension.
"""


def _read_combined_marker(repo_path: Path) -> dict | None:
    marker = repo_path / ".review" / "combined.yaml"
    if not marker.exists():
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(marker.read_text()))
    except Exception:
        return None


def run_review_matrix(
    *,
    mr_iid: int,
    project_path: str,
    claude: ClaudeCodeClient | None = None,
    repo_path: Path | None = None,
    combined: bool = True,
    base: str = "main",
) -> ReviewResult:
    """Run all MUST dimension reviews. Fail-closed on any error.

    Default `combined=True`: ONE CLI invocation evaluates all 7 dimensions in
    a single agent session. ~5x faster than per-dim calls (cold-start once).

    Set `combined=False` for the legacy per-dim mode (kept for testing).
    """
    import time

    claude = claude or ClaudeCodeClient()
    if repo_path is None:
        raise ValueError("repo_path is required for real reviewer")

    if not combined:
        return _run_per_dimension(
            mr_iid=mr_iid, project_path=project_path, claude=claude, repo_path=repo_path
        )

    print(
        f"[reviewer] combined mode: 1 CLI call for {len(MUST_DIMENSIONS)} dims on MR #{mr_iid}",
        flush=True,
    )
    t0 = time.monotonic()
    prompt = _COMBINED_PROMPT_TEMPLATE.format(cwd=str(repo_path), mr_iid=mr_iid, base=base)
    cli_result = claude.run(prompt=prompt, cwd=repo_path)
    elapsed = time.monotonic() - t0
    print(
        f"[reviewer] CLI exited rc={cli_result.returncode} in {elapsed:.1f}s",
        flush=True,
    )

    if cli_result.returncode != 0:
        results = dict.fromkeys(MUST_DIMENSIONS, "FAIL")
        reasons = dict.fromkeys(MUST_DIMENSIONS, f"subprocess error rc={cli_result.returncode}")
        return ReviewResult(
            all_passed=False,
            dimension_results=results,
            failed_dimensions=list(MUST_DIMENSIONS),
            reasons=reasons,
        )

    marker = _read_combined_marker(repo_path)
    if marker is None or "results" not in marker:
        results = dict.fromkeys(MUST_DIMENSIONS, "FAIL")
        reasons = dict.fromkeys(MUST_DIMENSIONS, "no combined marker produced")
        return ReviewResult(
            all_passed=False,
            dimension_results=results,
            failed_dimensions=list(MUST_DIMENSIONS),
            reasons=reasons,
        )

    raw_results = marker.get("results", {}) or {}
    raw_reasons = marker.get("reasons", {}) or {}
    dimension_results: dict[str, str] = {}
    reasons: dict[str, str] = {}
    failed: list[str] = []
    for dim in MUST_DIMENSIONS:
        status = str(raw_results.get(dim, "FAIL")).upper()
        if status not in ("PASS", "FAIL"):
            status = "FAIL"
        dimension_results[dim] = status
        reasons[dim] = str(raw_reasons.get(dim, ""))
        glyph = "✓" if status == "PASS" else "✗"
        print(f"[reviewer]   {glyph} {dim}: {status} — {reasons[dim]}", flush=True)
        if status != "PASS":
            failed.append(dim)

    summary = "ALL PASSED" if not failed else f"FAILED on {failed}"
    print(f"[reviewer] {summary}", flush=True)

    return ReviewResult(
        all_passed=not failed,
        dimension_results=dimension_results,
        failed_dimensions=failed,
        reasons=reasons,
    )


def _run_per_dimension(
    *,
    mr_iid: int,
    project_path: str,
    claude: ClaudeCodeClient,
    repo_path: Path,
) -> ReviewResult:
    """Legacy per-dimension mode — one CLI call per dim. Slower."""
    import time

    dimension_results: dict[str, str] = {}
    reasons: dict[str, str] = {}
    failed: list[str] = []

    total = len(MUST_DIMENSIONS)
    print(
        f"[reviewer] per-dim mode: {total} dimensions on MR #{mr_iid} ({project_path})",
        flush=True,
    )
    overall_start = time.monotonic()

    for idx, dim in enumerate(MUST_DIMENSIONS, start=1):
        print(f"[reviewer {idx}/{total}] {dim}: invoking CLI...", flush=True)
        t0 = time.monotonic()
        status, reason = _review_one(dim=dim, claude=claude, repo_path=repo_path)
        elapsed = time.monotonic() - t0
        dimension_results[dim] = status
        reasons[dim] = reason
        glyph = "✓" if status == "PASS" else "✗"
        print(
            f"[reviewer {idx}/{total}] {dim}: {glyph} {status} ({elapsed:.1f}s) — {reason}",
            flush=True,
        )
        if status != "PASS":
            failed.append(dim)

    print(
        f"[reviewer] per-dim done in {time.monotonic() - overall_start:.1f}s",
        flush=True,
    )

    return ReviewResult(
        all_passed=not failed,
        dimension_results=dimension_results,
        failed_dimensions=failed,
        reasons=reasons,
    )
