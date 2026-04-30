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
from flow.prompts import load_prompt

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
        "spec_compliance — For EACH item in `task.spec.quality_criteria`, locate the diff "
        "hunk and/or test that satisfies it. PASS only when every item has clear evidence. "
        "FAIL listing the specific unmet criteria. Do NOT invent additional requirements "
        "not in the spec. Do NOT FAIL because of stylistic preferences."
    ),
    "test_quality": (
        "test_quality — Every test added/modified must (a) contain non-empty assertions on "
        "real values, (b) NOT be tautological (`assert True`, `assert x == x`), (c) NOT have "
        "been weakened to fit a buggy implementation, and (d) actually exercise the new "
        "production code path. PASS when these hold. FAIL with the offending test name."
    ),
    "security": (
        "security — Scan the diff for OWASP top-10 risks: SQL/command injection, hardcoded "
        "secrets, missing auth/authz checks, sensitive-data leaks in logs, unsafe "
        "deserialisation, SSRF, path traversal. If none introduced, PASS with reason "
        "'no security-relevant changes' (and a one-line justification). Do NOT FAIL on "
        "speculative risks unrelated to the diff."
    ),
    "consistency": (
        "consistency — Check naming, file layout, and style match neighbouring code in the "
        "same module (look at sibling files). Look for lint/format violations the project "
        "enforces. PASS when conventions are followed. FAIL only when there is a clear "
        "deviation; don't FAIL on minor preferences."
    ),
    "migration_safety": (
        "migration_safety — If the diff includes a DB schema change, data migration, or "
        "format change in persisted state, verify it is reversible and has up/down logic. "
        "If no such change exists, PASS with reason 'no migration in this diff'."
    ),
    "performance": (
        "performance — Look for obvious regressions (N+1 queries, sync calls in hot loops, "
        "unbounded recursion, large in-memory copies). PASS unless you can point to a "
        "specific concrete regression. If no benchmarking baseline exists, PASS with "
        "reason 'no baseline; no obvious regression in diff'."
    ),
    "documentation_sync": (
        "documentation_sync — When code changes affect public behaviour visible to users "
        "or operators (CLI flags, config keys, public APIs, README'd flows), verify the "
        "corresponding docs/README/code-comments were updated in the SAME diff. If the "
        "change is purely internal (refactor, internal helper, test-only), PASS with "
        "reason 'internal-only change; no doc impact'."
    ),
}


_COMBINED_PROMPT_TEMPLATE = load_prompt("reviewer")


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

    log_dir = repo_path.parent / "host-logs" / f"reviewer-iter{iteration}"
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
