"""Planner subprocess (spec §5).

Pure function: input.yaml → result.yaml. Planner does NOT touch GitHub API.
The Coordinator parses result.yaml and applies side effects via reconciler.
"""

import os
import tempfile
import time
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from flow.clients import AgentClient
from flow.metrics import EVENTS, emit, emit_llm_call
from flow.prompts import load_prompt

_PROMPT_TEMPLATE = load_prompt("planner")


@dataclass
class PlannerResult:
    status: str                        # "ok" | "blocked" | "done" | "no_marker"
    desired_plan: list[dict] = field(default_factory=list)
    actions: dict = field(default_factory=dict)
    summary: str = ""
    blocker: dict | None = None
    raw: dict | None = None
    duration_ms: int = 0


def _serialize_yaml(data: Any) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    buf = StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def _clone_repo(url: str, to_path: Path, branch: str | None = None):
    from git import Repo

    if branch:
        return Repo.clone_from(url, to_path, branch=branch)
    return Repo.clone_from(url, to_path)


def _read_marker(workdir: Path) -> dict | None:
    marker = workdir / ".flow" / "result.yaml"
    if not marker.exists():
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(marker.read_text()))
    except Exception:
        return None


_TASK_ID_RE = __import__("re").compile(r"^T-[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_planner_marker(marker: Any) -> list[str]:
    """Strict shape validation for `result.yaml` (spec §5.4).

    Returns a list of human-readable error strings. Empty list means valid.
    The validator is intentionally strict so that obvious mistakes (missing
    task_id, wrong status, ill-typed fields) trigger an automatic retry of
    the Planner with a precise feedback section appended to the prompt.
    """
    errors: list[str] = []
    if not isinstance(marker, dict):
        return ["result.yaml top-level must be a YAML mapping"]

    schema = marker.get("schema_version")
    if schema != 1:
        errors.append(
            f"`schema_version` must be the integer 1, got {schema!r}"
        )

    status = marker.get("status")
    if status not in ("ok", "done", "blocked"):
        errors.append(
            f"`status` must be one of 'ok' | 'done' | 'blocked', got {status!r}"
        )
        return errors

    if status == "ok":
        desired = marker.get("desired_plan")
        if not isinstance(desired, list):
            errors.append("`status: ok` requires `desired_plan` to be a list")
            desired = []
        if not desired:
            errors.append(
                "`desired_plan` is empty — emit at least one task, "
                "or use `status: done` (all work finished) / "
                "`status: blocked` (need human input)"
            )
        seen_ids: set[str] = set()
        for i, t in enumerate(desired):
            prefix = f"desired_plan[{i}]"
            if not isinstance(t, dict):
                errors.append(f"{prefix} must be a mapping")
                continue
            tid = t.get("task_id")
            if not isinstance(tid, str) or not tid.strip():
                errors.append(
                    f"{prefix}.task_id must be a non-empty string "
                    "(format `T-<kebab-case-slug>`)"
                )
            elif not _TASK_ID_RE.match(tid):
                errors.append(
                    f"{prefix}.task_id={tid!r} does not match "
                    "`T-<lowercase-kebab-case>` (e.g. `T-readme-usage-guide`)"
                )
            elif tid in seen_ids:
                errors.append(f"{prefix}.task_id={tid!r} is duplicated")
            else:
                seen_ids.add(tid)
            spec = t.get("spec")
            if not isinstance(spec, dict):
                errors.append(f"{prefix}.spec must be a mapping")
            else:
                goal = spec.get("goal")
                if not isinstance(goal, str) or not goal.strip():
                    errors.append(
                        f"{prefix}.spec.goal must be a non-empty string "
                        "(one-sentence task title)"
                    )
                qc = spec.get("quality_criteria")
                if not isinstance(qc, list) or not qc:
                    errors.append(
                        f"{prefix}.spec.quality_criteria must be a non-empty "
                        "list of acceptance bullets the Reviewer will check"
                    )
                elif any(not isinstance(c, str) or not c.strip() for c in qc):
                    errors.append(
                        f"{prefix}.spec.quality_criteria entries must each "
                        "be non-empty strings"
                    )
                steps = spec.get("steps")
                if steps is not None and not isinstance(steps, list):
                    errors.append(
                        f"{prefix}.spec.steps must be a list of "
                        "{{id, description, status}} mappings (or omitted)"
                    )
                constraints = spec.get("constraints")
                if constraints is not None and not isinstance(constraints, dict):
                    errors.append(f"{prefix}.spec.constraints must be a mapping")
            deps = t.get("deps")
            if deps is not None and not isinstance(deps, list):
                errors.append(f"{prefix}.deps must be a list of task_id strings")
            elif isinstance(deps, list):
                for j, d in enumerate(deps):
                    if not isinstance(d, str) or not d.strip():
                        errors.append(
                            f"{prefix}.deps[{j}] must be a non-empty task_id string"
                        )

        # Cross-task: deps must reference task_ids in the same desired_plan
        # (or task_ids that already exist — Planner can't see those statically,
        # so we only check intra-batch references here).
        for i, t in enumerate(desired):
            if not isinstance(t, dict):
                continue
            for d in t.get("deps") or []:
                if isinstance(d, str) and d.startswith("T-") and d not in seen_ids:
                    # Could be referencing an existing task — only flag if it
                    # is obviously a typo of one in this batch (skip for now).
                    pass

        actions = marker.get("actions")
        if actions is not None:
            if not isinstance(actions, dict):
                errors.append("`actions` must be a mapping (or omitted)")
            else:
                ms = actions.get("modify_specs")
                if ms is not None:
                    if not isinstance(ms, list):
                        errors.append("`actions.modify_specs` must be a list")
                    else:
                        for i, p in enumerate(ms):
                            mp = f"actions.modify_specs[{i}]"
                            if not isinstance(p, dict):
                                errors.append(f"{mp} must be a mapping")
                                continue
                            if (not isinstance(p.get("task_id"), str)
                                    or not p["task_id"].strip()):
                                errors.append(
                                    f"{mp}.task_id must be a non-empty string"
                                )
                            if "patch" in p and not isinstance(p["patch"], dict):
                                errors.append(f"{mp}.patch must be a mapping")
                ct = actions.get("cancel_tasks")
                if ct is not None and not isinstance(ct, list):
                    errors.append("`actions.cancel_tasks` must be a list of task_ids")
                ovr = actions.get("override_review")
                if ovr is not None and not isinstance(ovr, list):
                    errors.append("`actions.override_review` must be a list")

    elif status == "done":
        summary = marker.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(
                "`status: done` requires a non-empty `summary` string "
                "describing what the goal accomplished"
            )

    elif status == "blocked":
        blocker = marker.get("blocker")
        if not isinstance(blocker, dict):
            errors.append("`status: blocked` requires a `blocker` mapping")
        else:
            q = blocker.get("question")
            if not isinstance(q, str) or not q.strip():
                errors.append(
                    "`blocker.question` must be a non-empty string "
                    "(the precise question for the human)"
                )

    return errors


def _build_retry_feedback(
    *,
    attempt: int,
    reason: str,
    errors: list[str],
    marker: Any,
) -> str:
    """Render a feedback block to prepend to the prompt on retry."""
    yaml = YAML()
    yaml.default_flow_style = False
    buf = StringIO()
    if marker is not None:
        try:
            yaml.dump(marker, buf)
            rendered = buf.getvalue()
        except Exception:
            rendered = repr(marker)
    else:
        rendered = "(no result.yaml was written by the previous attempt)"

    bullets = "\n".join(f"  - {e}" for e in errors) or "  - (no detail)"
    return (
        f"⚠️  This is retry attempt #{attempt}. The previous attempt FAILED "
        "validation and its output was discarded.\n\n"
        f"Failure reason: {reason}\n\n"
        "Validation errors (fix EVERY one of these):\n"
        f"{bullets}\n\n"
        "Previous (rejected) result.yaml content:\n"
        "```yaml\n"
        f"{rendered}"
        "```\n\n"
        "Re-read Step 1 → Step 6 above, then write a CORRECTED "
        f"`{{workdir}}/.flow/result.yaml`. Do NOT repeat the mistakes listed "
        "above. If you cannot satisfy a validation rule (e.g. you genuinely "
        "have no tasks to plan), use `status: done` with a `summary`, or "
        "`status: blocked` with a precise `blocker.question` — those are "
        "always valid escape hatches.\n"
    )


def run_planner(
    *,
    repo,
    goal_issue_number: int,
    input_bundle: dict,
    base_branch: str,
    client: AgentClient,
    workdir: Path | None = None,
) -> PlannerResult:
    """Run Planner in an isolated workdir. Returns parsed result.

    Side effects are applied by the Reconciler — Planner only writes result.yaml.
    """
    workdir = workdir or Path(
        tempfile.mkdtemp(prefix=f"flow-planner-G{goal_issue_number}-")
    )
    repo_path = workdir / "repo"
    flow_dir = workdir / ".flow"
    flow_dir.mkdir(parents=True, exist_ok=True)

    # Clone read-only — Planner doesn't need write
    sw_git_token = (os.environ.get("FLOW_GIT_TOKEN")
        or os.environ.get("COPILOT_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN"))
    if sw_git_token and repo.clone_url.startswith("https://"):
        clone_url = repo.clone_url.replace(
            "https://", f"https://x-access-token:{sw_git_token}@", 1
        )
    else:
        clone_url = repo.clone_url

    try:
        _clone_repo(clone_url, repo_path, branch=base_branch)
    except Exception as exc:
        return PlannerResult(
            status="no_marker",
            blocker={"blocker_type": "clone_failed", "reason": str(exc)},
        )

    # Write input.yaml in workdir (Planner reads relative paths)
    (workdir / "input.yaml").write_text(_serialize_yaml(input_bundle))

    # Symlink/copy a `.flow` writable dir inside repo for the marker
    (repo_path / ".flow").mkdir(exist_ok=True)
    marker_path = workdir / ".flow" / "result.yaml"

    # Tell the planner where input is via an env var
    env = {"FLOW_PLANNER_WORKDIR": str(workdir)}

    max_attempts = max(1, int(os.environ.get("FLOW_PLANNER_MAX_ATTEMPTS", "3")))
    prior_feedback = (
        "(This is the first attempt — no prior feedback. Follow the steps "
        "above carefully and write a valid `result.yaml`.)"
    )
    last_marker: dict | None = None
    last_errors: list[str] = []
    last_returncode: int = 0
    last_stdout: str = ""
    last_stderr: str = ""
    total_elapsed_ms = 0

    for attempt in range(1, max_attempts + 1):
        # Clear any stale marker from a previous attempt.
        try:
            marker_path.unlink()
        except FileNotFoundError:
            pass

        prompt = _PROMPT_TEMPLATE.format(
            workdir=str(workdir),
            prior_attempts_feedback=prior_feedback,
        )
        log_dir = workdir / "host-logs" / "planner" / f"attempt-{attempt}"
        t0 = time.monotonic()
        cli_result = client.run(prompt=prompt, cwd=workdir, env=env, log_dir=log_dir)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        total_elapsed_ms += elapsed_ms
        last_returncode = cli_result.returncode
        last_stdout = cli_result.stdout or ""
        last_stderr = cli_result.stderr or ""

        emit_llm_call(
            role="planner",
            goal=goal_issue_number,
            task_id=None,
            model=client.name,
            duration_ms=elapsed_ms,
            exit_status="ok" if cli_result.returncode == 0 else "non_zero",
        )
        emit(EVENTS.PLANNER_DISPATCHED, issue_iid=goal_issue_number,
             reason=input_bundle.get("invocation_reason"))

        marker = _read_marker(workdir)
        if marker is None:
            last_marker = None
            last_errors = ["The previous attempt did not write `result.yaml` at all."]
            if attempt >= max_attempts:
                break
            print(
                f"[planner] attempt {attempt}/{max_attempts} produced no marker; "
                "retrying with feedback",
                flush=True,
            )
            prior_feedback = _build_retry_feedback(
                attempt=attempt + 1,
                reason="result.yaml was not written",
                errors=last_errors,
                marker=None,
            )
            continue

        errors = validate_planner_marker(marker)
        if not errors:
            last_marker = marker
            last_errors = []
            break

        last_marker = marker
        last_errors = errors
        if attempt >= max_attempts:
            break
        print(
            f"[planner] attempt {attempt}/{max_attempts} failed validation "
            f"with {len(errors)} error(s); retrying",
            flush=True,
        )
        for e in errors:
            print(f"[planner]   - {e}", flush=True)
        prior_feedback = _build_retry_feedback(
            attempt=attempt + 1,
            reason="result.yaml failed strict validation",
            errors=errors,
            marker=marker,
        )

    elapsed_ms = total_elapsed_ms

    if last_marker is None:
        return PlannerResult(
            status="no_marker",
            blocker={
                "blocker_type": "no_result_marker",
                "returncode": last_returncode,
                "stdout": last_stdout[-2000:],
                "stderr": last_stderr[-2000:],
                "attempts": max_attempts,
            },
            duration_ms=elapsed_ms,
        )

    if last_errors:
        return PlannerResult(
            status="no_marker",
            blocker={
                "blocker_type": "invalid_marker",
                "errors": last_errors,
                "attempts": max_attempts,
                "marker": last_marker,
            },
            duration_ms=elapsed_ms,
        )

    marker = last_marker

    status = str(marker.get("status", "")).lower()
    if status == "ok":
        return PlannerResult(
            status="ok",
            desired_plan=list(marker.get("desired_plan") or []),
            actions=dict(marker.get("actions") or {}),
            raw=marker,
            duration_ms=elapsed_ms,
        )
    if status == "done":
        return PlannerResult(
            status="done",
            summary=str(marker.get("summary", "")),
            raw=marker,
            duration_ms=elapsed_ms,
        )
    if status == "blocked":
        return PlannerResult(
            status="blocked",
            blocker=dict(marker.get("blocker") or {}),
            raw=marker,
            duration_ms=elapsed_ms,
        )
    return PlannerResult(
        status="no_marker",
        blocker={"blocker_type": "unknown_status", "raw": marker},
        duration_ms=elapsed_ms,
    )


def build_input_bundle(
    *,
    invocation_reason: str,
    goal_issue,
    goal_body,
    children: list[dict],
    repo_context: dict | None = None,
    arbitration_context: dict | None = None,
    replan_hint: str | None = None,
    replan_target: str | None = None,
    authoring_user: str | None = None,
) -> dict:
    """Build Planner input bundle (spec §5.3)."""
    bundle: dict = {
        "schema_version": 1,
        "invocation_reason": invocation_reason,
        "goal": {
            "issue": goal_issue.number,
            "title": goal_issue.title,
            "body_prose": (goal_body.prose or "")[:8000],
            "manifest": [m.to_dict() for m in goal_body.manifest],
            "authoring_user": authoring_user,
        },
        "children": children,
        "repo_context": repo_context or {},
    }
    if arbitration_context is not None:
        bundle["arbitration_context"] = arbitration_context
    if replan_hint is not None:
        bundle["replan_hint"] = replan_hint
    if replan_target is not None:
        bundle["replan_target"] = replan_target
    return bundle
