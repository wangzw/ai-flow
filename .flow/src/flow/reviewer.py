"""Reviewer matrix (spec §7).

7 dimensions, MUST + MAY split. Channel discipline §11: Reviewer reads only
spec / diff / tests / code-comments. Implementer's PR description, commit
messages, and self-summary are NEVER provided. Reviewers are independent
between dimensions.

Default: combined mode (single CLI call evaluates all dimensions). The
inherited prompt design from software-workflow has been validated.
"""

import time
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from flow.clients import AgentClient
from flow.metrics import EVENTS, emit, emit_llm_call

MUST_DIMENSIONS = (
    "spec_compliance",
    "test_quality",
    "security",
    "consistency",
    "migration_safety",
)
MAY_DIMENSIONS = ("performance", "documentation_sync")
ALL_DIMENSIONS = MUST_DIMENSIONS + MAY_DIMENSIONS


@dataclass
class ReviewResult:
    all_must_passed: bool
    dimension_results: dict[str, str]
    failed_dimensions: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    iteration: int = 0
    aggregate_yaml: str = ""


_DIMENSION_PROMPTS: dict[str, str] = {
    "spec_compliance": (
        "spec_compliance — Verify EVERY task.spec.quality_criteria item is satisfied "
        "by the diff (code + tests). Do NOT invent extra requirements."
    ),
    "test_quality": (
        "test_quality — Tests have non-empty assertions, are not tautologies, were not "
        "weakened to fit a buggy implementation, and exercise the actual behavior."
    ),
    "security": (
        "security — OWASP top-10 risks (injection, auth, data exposure)."
    ),
    "consistency": (
        "consistency — Lint clean, naming/style/conventions follow project norms."
    ),
    "migration_safety": (
        "migration_safety — DB/data migration is safe & reversible. If no migration, "
        "PASS with reason 'no migration'."
    ),
    "performance": (
        "performance — Regression vs baseline. If no baseline, PASS with reason 'no baseline'."
    ),
    "documentation_sync": (
        "documentation_sync — Docs/README/comments consistent with code changes."
    ),
}


_COMBINED_PROMPT_TEMPLATE = """You are a senior code reviewer. Review the diff in this repo
against the dimensions below.

Project root: {cwd}
PR #: {pr}
Task ID: {task_id}
Base branch: {base}
Iteration: {iteration}

# Task spec (the ONLY source of requirements; spec_compliance judges against this)

```yaml
{task_spec_yaml}
```

# What to read (white-list — spec §11)

- The task spec above
- The diff: `git diff origin/{base}..HEAD`
- All test files added/modified
- Code comments in modified files

# What you MUST NOT read (channel discipline — spec §11)

- git commit messages
- the PR description / title
- the Implementer's `.agent/result.yaml` summary
- any other Reviewer dimension's verdict

# Dimensions

{dimensions_block}

# Iteration history (this PR; only your prior verdicts on these dimensions)

{prior_history_yaml}

# Output (REQUIRED)

Write ONE marker file `.review/aggregate.yaml` with this exact structure:

  mkdir -p .review
  cat > .review/aggregate.yaml <<'EOF'
  schema_version: 1
  iteration: {iteration}
  dimensions:
    - dim: spec_compliance
      verdict: pass     # or fail
      reason: <one-line>
{example_dims}  EOF

Then exit. Be efficient: read each file once.
"""


def _serialize_yaml(data) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    buf = StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def _read_aggregate(repo_path: Path) -> dict | None:
    marker = repo_path / ".review" / "aggregate.yaml"
    if not marker.exists():
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(marker.read_text()))
    except Exception:
        return None


def run_review_matrix(
    *,
    pr_number: int,
    task_id: str,
    task_spec: dict,
    repo_path: Path,
    client: AgentClient,
    base_branch: str = "main",
    iteration: int = 1,
    enabled_must: tuple[str, ...] = MUST_DIMENSIONS,
    enabled_may: tuple[str, ...] = (),
    prior_history: list[dict] | None = None,
) -> ReviewResult:
    """Run combined-mode reviewer; fail-closed on missing/invalid marker."""
    enabled = list(enabled_must) + list(enabled_may)
    dims_block = "\n".join(f"- {_DIMENSION_PROMPTS[d]}" for d in enabled)
    example_dims = "".join(
        f"    - dim: {d}\n      verdict: pass\n      reason: <one-line>\n" for d in enabled[1:]
    )

    prompt = _COMBINED_PROMPT_TEMPLATE.format(
        cwd=str(repo_path),
        pr=pr_number,
        task_id=task_id,
        base=base_branch,
        iteration=iteration,
        task_spec_yaml=_serialize_yaml(task_spec),
        dimensions_block=dims_block,
        prior_history_yaml=_serialize_yaml(prior_history or []),
        example_dims=example_dims,
    )

    log_dir = repo_path / ".flow-logs" / f"reviewer-iter{iteration}"
    print(f"[reviewer] PR #{pr_number} iter={iteration} dims={enabled}", flush=True)
    t0 = time.monotonic()
    cli_result = client.run(prompt=prompt, cwd=repo_path, log_dir=log_dir)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    emit_llm_call(
        role="reviewer",
        goal=None,
        task_id=task_id,
        model=client.name,
        duration_ms=elapsed_ms,
        exit_status="ok" if cli_result.returncode == 0 else "non_zero",
        iteration=iteration,
    )

    if cli_result.returncode != 0:
        results = {d: "FAIL" for d in enabled}
        reasons = {d: f"subprocess error rc={cli_result.returncode}" for d in enabled}
        emit(EVENTS.REVIEWER_FAILED, pr_number=pr_number, failed_dimensions=enabled)
        return ReviewResult(
            all_must_passed=False,
            dimension_results=results,
            failed_dimensions=list(enabled),
            reasons=reasons,
            iteration=iteration,
        )

    agg = _read_aggregate(repo_path)
    if agg is None or "dimensions" not in agg:
        results = {d: "FAIL" for d in enabled}
        reasons = {d: "no aggregate marker produced" for d in enabled}
        emit(EVENTS.REVIEWER_FAILED, pr_number=pr_number, failed_dimensions=enabled,
             reason="no_marker")
        return ReviewResult(
            all_must_passed=False,
            dimension_results=results,
            failed_dimensions=list(enabled),
            reasons=reasons,
            iteration=iteration,
        )

    dim_map = {d.get("dim"): d for d in (agg.get("dimensions") or []) if isinstance(d, dict)}
    results: dict[str, str] = {}
    reasons: dict[str, str] = {}
    failed: list[str] = []

    for d in enabled:
        record = dim_map.get(d) or {}
        verdict = str(record.get("verdict", "fail")).lower()
        verdict_norm = "PASS" if verdict == "pass" else "FAIL"
        results[d] = verdict_norm
        reasons[d] = str(record.get("reason", ""))
        if verdict_norm != "PASS":
            failed.append(d)

    must_failed = [d for d in failed if d in enabled_must]
    all_must_passed = not must_failed

    if all_must_passed:
        emit(EVENTS.REVIEWER_PASSED, pr_number=pr_number, iteration=iteration)
    else:
        emit(EVENTS.REVIEWER_FAILED, pr_number=pr_number, failed_dimensions=failed,
             iteration=iteration)

    return ReviewResult(
        all_must_passed=all_must_passed,
        dimension_results=results,
        failed_dimensions=failed,
        reasons=reasons,
        iteration=iteration,
        aggregate_yaml=_serialize_yaml(agg),
    )
