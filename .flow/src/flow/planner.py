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

_PROMPT_TEMPLATE = """You are the Planner agent in the ai-flow framework.

You are a reactive **reconciler**: each invocation, you read full state and
output the full desired plan. You do NOT touch GitHub API or files outside
this workdir. You write exactly ONE marker file: `.flow/result.yaml`.

# Workdir layout

- `{workdir}/repo/`     — read-only clone of the project (you may explore it)
- `{workdir}/input.yaml` — invocation context (read this first)
- `{workdir}/result.yaml` — your output goes here

# What you must do

1. Read `{workdir}/input.yaml`. It contains:
   - `invocation_reason`: initial | child_done | child_blocker | replan_command | review_arbitration
   - `goal`: the root goal Issue (title, body_prose, manifest)
   - `children`: list of current task Issues with state, spec, blocker
   - `arbitration_context` (only when invocation_reason=review_arbitration)
   - `replan_hint` (only when invocation_reason=replan_command)
   - `repo_context`: language, recent commits, file tree

2. Decide ONE of three statuses:
   - `ok`: emit a desired_plan (FULL state — every task that should exist)
   - `done`: every child is in a terminal state AND goal is truly satisfied
   - `blocked`: you cannot decompose further without human input

3. Write `.flow/result.yaml` with this schema:

```yaml
schema_version: 1
status: ok | blocked | done

# status==ok
desired_plan:
  - task_id: T-<slug>          # stable identity, must be unique within goal
    spec:
      goal: "<one-line>"
      constraints:
        preconditions: ["..."]
        capabilities: ["module:..."]   # which modules this task may modify
      quality_criteria:        # testable acceptance items
        - "..."
      steps:                   # optional; high-level
        - {{id: s1, description: "...", status: pending}}
    deps: [T-other]            # task_ids this task depends on
    parent_task_id: null       # null = directly under root

actions:                       # OPTIONAL; explicit non-derivable actions
  modify_specs:
    - task_id: T-...
      reason: "..."
      patch: {{ quality_criteria: [...] }}
      reset_review_iteration: true
  override_review:
    - task_id: T-...
      verdict: pass
      reason: "..."
  cancel_tasks: [T-orphan]

# status==done
summary: |
  <multi-line summary of what was achieved across the tree>

# status==blocked
blocker:
  question: "..."
  options: [{{id: A, desc: "..."}}]
  custom_allowed: true
  agent_state:
    stage: planner
    blocker_type: goal_too_vague | conflicting_constraints | external_decision_needed
```

# Important rules

- **Reconcile, don't diff.** Always emit the full desired_plan, including tasks
  that are already done (with their current state).
- **Stable task_ids.** Once a task_id is in the manifest, reuse it; never rename.
- **Minimal trees first.** Prefer 1–3 tasks for simple goals. Only decompose
  further when complexity demands.
- **Hard guard for done.** Never declare `status: done` while any task is in
  a non-terminal state.
- **Quality criteria must be testable.** `spec_compliance` Reviewer judges
  against this; vague criteria cause review death-loops.

# Failure mode

If `.flow/result.yaml` is missing or malformed when you exit, the Coordinator
treats this as failed-env (fail-closed). Always write the marker.
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
    sw_git_token = (os.environ.get("SW_GIT_TOKEN")
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
    # Ask agent to write to workdir/.flow/result.yaml — give absolute path
    prompt = _PROMPT_TEMPLATE.format(workdir=str(workdir))

    # Tell the planner where input is via an env var
    env = {"FLOW_PLANNER_WORKDIR": str(workdir)}

    log_dir = repo_path / ".flow-logs" / "planner"
    t0 = time.monotonic()
    cli_result = client.run(prompt=prompt, cwd=workdir, env=env, log_dir=log_dir)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

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
        return PlannerResult(
            status="no_marker",
            blocker={
                "blocker_type": "no_result_marker",
                "returncode": cli_result.returncode,
                "stdout": (cli_result.stdout or "")[-2000:],
                "stderr": (cli_result.stderr or "")[-2000:],
            },
            duration_ms=elapsed_ms,
        )

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
