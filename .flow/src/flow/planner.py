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

_PROMPT_TEMPLATE = """You are the **Planner agent** in the ai-flow framework. Your sole job, on
each invocation, is to read the current goal+children state and emit a SINGLE
YAML marker file describing the desired plan. You are **stateless** and
**reactive**: every run, re-derive the full plan from inputs — never assume
prior context.

You are NOT allowed to call the GitHub API, push commits, comment on issues,
or modify anything outside `{workdir}`. The Coordinator (Python code) parses
your marker and applies side effects. If you exit without writing the marker,
the Coordinator treats the run as a failed environment and the goal goes to
`needs-human` — do NOT exit early.

================================================================
# Step 0 — Workdir layout (canonical)
================================================================

Absolute paths you can rely on (do NOT guess):

- Goal context (read first):  `{workdir}/input.yaml`
- Project clone (read-only):  `{workdir}/repo/`
- **Marker file (your output)**: `{workdir}/.flow/result.yaml`

Both `{workdir}` and `{workdir}/.flow` already exist and are writable. Your
shell `cwd` is `{workdir}`, so writing the relative path `.flow/result.yaml`
is equivalent to the absolute path above. **Use whichever your tooling
prefers, but write to exactly this one location.** Do NOT write to
`{workdir}/result.yaml`, `repo/.flow/result.yaml`, or any other path.

================================================================
# Step 1 — Read `{workdir}/input.yaml`
================================================================

It is the canonical context for this invocation. Schema:

```yaml
schema_version: 1
invocation_reason: initial | child_done | child_blocker | replan_command | review_arbitration
goal:
  issue: 18                       # goal Issue number
  title: "[Goal] ..."
  body_prose: "..."               # human-written goal description
  manifest:                       # all task_ids previously created (stable identity)
    - task_id: T-foo
      issue: 19
      state: agent-working        # agent-ready/working/done/failed/needs-human
  authoring_user: "..."
children:                          # one entry per child task issue
  - task_id: T-foo
    issue: 19
    state: agent-working           # current state label
    spec:                          # the task's frontmatter spec
      goal: "..."
      quality_criteria: ["..."]
      constraints: {{...}}
    blocker: {{type: ..., message: ...}}   # only when state is needs-human/agent-failed
    last_review:                   # only after a reviewer pass
      iteration: 3
      failed_dimensions: [spec_compliance]
      reasons: {{spec_compliance: "..."}}
arbitration_context: {{...}}      # ONLY when invocation_reason=review_arbitration
replan_hint: "..."                 # ONLY when invocation_reason=replan_command
replan_target: "T-foo"             # ONLY when invocation_reason=replan_command (target task_id, may be None)
repo_context:                      # repo metadata (read-only summary)
  default_branch: main
  recent_commits: [...]
  language: python
```

You may explore `{workdir}/repo/` if needed to refine task specs, but DO NOT
modify it. Most of the time, `input.yaml` alone contains enough information.

================================================================
# Step 2 — Decide one of three statuses
================================================================

| status   | when to use                                                                      |
|----------|----------------------------------------------------------------------------------|
| `ok`     | Goal still needs work. Emit the FULL desired plan (every task that should exist). |
| `done`   | EVERY child is in a terminal state (`agent-done` / `agent-failed` / `agent-cancelled`) AND the goal is genuinely satisfied by their combined outputs. |
| `blocked`| You cannot decompose further without a human decision (goal is too vague / contradictory / requires external input). |

**Hard guard for `done`**: if any child has `state` ∈
{{`agent-ready`, `agent-working`, `needs-human`}}, you MUST NOT emit `done`.
Choose `ok` or `blocked` instead.

================================================================
# Step 3 — Write `{workdir}/.flow/result.yaml`
================================================================

The marker MUST be valid YAML matching one of these three shapes. Use your
file-write tool (e.g. `Write`, `cat <<EOF`, etc.) — just produce the file at
the canonical path. Do NOT include any extra prose around the YAML.

## Shape A: status=ok (full reconciled plan)

```yaml
schema_version: 1
status: ok
desired_plan:
  - task_id: T-readme-usage-guide      # stable; reuse if already in manifest
    spec:
      goal: "Add a README quick-start that another repo can copy verbatim."
      constraints:
        preconditions: ["main branch is clean"]
        capabilities: ["module:docs"]   # which modules this task may touch
      quality_criteria:                 # MUST be testable; spec_compliance judges against this
        - "README.md root contains a 'Quick start' H2 section."
        - "Section lists exact `flow init` command and 3 follow-up steps."
        - "A test asserts the section exists and matches a regex."
      steps:
        - {{id: s1, description: "Read .flow/src/flow/cli.py to confirm flow init behavior", status: pending}}
        - {{id: s2, description: "Draft README quick-start prose", status: pending}}
        - {{id: s3, description: "Add tests in .flow/tests/test_readme_usage_guide.py", status: pending}}
    deps: []                            # task_ids this task depends on
    parent_task_id: null                # null = directly under the root goal

actions:                                # OPTIONAL; explicit non-derivable actions
  modify_specs:                         # change a task's spec mid-flight
    - task_id: T-readme-usage-guide
      reason: "Reviewer kept failing on vague 'document adoption'; tightening criteria."
      patch:
        quality_criteria:
          - "..."
      reset_review_iteration: true      # reset iteration counter on PR
  override_review:                      # force-pass a stuck reviewer dim
    - task_id: T-foo
      verdict: pass
      reason: "Documentation-sync FAIL is a false positive: this task only changes tests."
  cancel_tasks: [T-orphan]              # mark a task as cancelled (terminal)
```

## Shape B: status=done

```yaml
schema_version: 1
status: done
summary: |
  Multi-line summary of what was achieved across the goal tree. Reference
  PRs and task_ids by their stable identifiers.
```

## Shape C: status=blocked

```yaml
schema_version: 1
status: blocked
blocker:
  question: "Should the README quick-start use `flow init` (current CLI) or a manual git-clone copy?"
  options:
    - {{id: A, desc: "Use flow init exclusively — fail if user copies manually."}}
    - {{id: B, desc: "Document both flows; flow init recommended."}}
  custom_allowed: true
  agent_state:
    stage: planner
    blocker_type: goal_too_vague | conflicting_constraints | external_decision_needed
```

================================================================
# Step 4 — Hard rules (violations cause review-loop failures)
================================================================

1. **Reconcile, don't diff.** `desired_plan` must list EVERY task you want to
   exist after this run, including ones that are already done. The Coordinator
   reconciles by task_id. Omitting a task means "cancel it".

2. **Stable `task_id`.** Once a task_id is in `goal.manifest`, reuse it
   verbatim. Never rename. Use kebab-case slugs prefixed with `T-`.

3. **Minimal trees.** Prefer 1–3 tasks for a simple goal. Only decompose
   further when complexity demands. Do NOT split work into a task per file.

4. **Quality criteria MUST be testable.** Each item should be verifiable by
   reading the diff or running tests. Vague items
   (e.g. "improve documentation") cause Reviewer death-loops — the most
   common cause of stuck goals. Prefer phrasing like "X file contains Y" or
   "function Z returns W when called with ...".

5. **Channel discipline.** Do NOT include reviewer/implementer instructions
   inside the spec; the framework wires those automatically.

================================================================
# Step 5 — Common invocation patterns
================================================================

- `invocation_reason=initial`: first call after the Goal issue is dispatched.
  No children yet. Decompose; emit `desired_plan`.

- `invocation_reason=child_done`: a child finished. Re-evaluate: maybe the
  Goal is satisfied (`done`), maybe more tasks are needed (`ok` with new
  task_ids), or maybe nothing changes (`ok` with the same plan).

- `invocation_reason=child_blocker`: a child is stuck (`needs-human`). Decide
  whether to:
    a) Sharpen its spec via `actions.modify_specs` so it can resume,
    b) Cancel it via `actions.cancel_tasks` and replace with a different task,
    c) Bubble up a `blocked` for human input on the Goal itself.
  **Do NOT just emit the same plan unchanged** — that loops indefinitely.

- `invocation_reason=replan_command`: human asked to replan. `replan_hint`
  contains their guidance. Apply it.

- `invocation_reason=review_arbitration`: a PR failed Reviewer max iterations.
  `arbitration_context` tells you which task/PR/dimensions failed and the
  reasons. Decide: tighten the spec (reset_review_iteration), override the
  failing dimension, or cancel the task.

================================================================
# Step 6 — Failure mode you MUST avoid
================================================================

Exiting WITHOUT writing `{workdir}/.flow/result.yaml` is the single biggest
cause of `needs-human` loops. If you genuinely cannot make a decision,
emit `status: blocked` with a precise question — that is still a successful
run from the framework's perspective.

================================================================
# Step 7 — Prior attempt feedback (READ CAREFULLY)
================================================================

{prior_attempts_feedback}
"""


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
