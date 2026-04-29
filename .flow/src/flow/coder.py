"""Implementer subprocess: clone repo, run agent, parse .agent/result.yaml, push & open PR.

Spec §6. Channel discipline §11: PR description is for humans; reviewer reads
only diff/tests/code-comments.
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
from flow.metrics import emit_llm_call

_PROMPT_TEMPLATE = """You are an Implementer agent. You produce a working code change for a
single well-specified task in this Git repository.

Project root: {cwd}
Task ID: {task_id}
Goal Issue: #{goal_issue}
Task Issue: #{task_issue}
Branch (already checked out): {branch}
Base branch: {base}

# Task spec

{task_spec_yaml}

# Goal context (read-only)

{goal_prose}

# Sibling artifacts (read-only)

{siblings_yaml}

# Channel discipline (HARD constraint per spec §11)

You produce four categories of artifacts, each with its own audience:

1. Code + comments       → Reviewer reads. Put non-trivial WHY here.
2. PR description        → humans read (review/release-notes/audit).
                          Reviewer agents will NOT read it.
3. Commit message        → humans/tooling read (conventional commits).
                          Reviewer will NOT read.
4. .agent/result.yaml    → Planner reads (brief self-summary).

# Validation

Read task.spec.quality_criteria. If they are too vague or contradictory to be
testable → write a `status: blocked` result with `blocker_type: spec_ambiguity`
and do NOT start coding.

# Steps

1. Implement the requested change. Follow existing patterns and conventions.
2. Write/extend tests that cover each quality_criterion (TDD when feasible).
3. For any non-obvious WHY (constraints, workarounds, invariants), add a code
   comment — Reviewer will only see the diff/tests/comments.
4. Iterate until tests pass locally.
5. `git add -A` and commit with a conventional-commits message.
6. Push the branch upstream.
7. Open a draft pull request with this body:

   ```
   ## Summary
   <1-3 sentences>

   ## Motivation / Context
   <why>

   ## Changes
   - <list>

   ## Testing
   <how validated>

   Closes #{task_issue}
   ```

# Output marker (REQUIRED)

When done — and ONLY when all tests pass and the PR is opened — write:

  mkdir -p .agent
  cat > .agent/result.yaml <<'EOF'
  schema_version: 1
  status: done
  artifacts:
    branch: {branch}
    pr_opened: true
    summary: |
      <one-paragraph self-summary for Planner>
  EOF

If you cannot proceed:

  cat > .agent/result.yaml <<'EOF'
  schema_version: 1
  status: blocked
  blocker:
    type: spec_ambiguity | cross_module_conflict | dep_unmet | tool_error | model_error | ask
    message: <one-line>
    details: {{}}
    question: <only when type=ask>
    options: []
  EOF

Then exit. Missing marker is treated as failed-env (fail-closed).
"""


@dataclass
class ImplementerResult:
    status: str  # "done" | "blocked" | "no_marker" | "subprocess_error"
    pr_number: int | None = None
    branch_name: str = ""
    summary: str = ""
    blocker: dict | None = None
    raw: dict | None = None
    workdir: Path | None = None
    duration_ms: int = 0
    extra: dict = field(default_factory=dict)


def _clone_repo(url: str, to_path: Path, branch: str | None = None):
    from git import Repo

    if branch:
        return Repo.clone_from(url, to_path, branch=branch)
    return Repo.clone_from(url, to_path)


def _push_branch(repo, branch_name: str):
    repo.git.push("--set-upstream", "origin", branch_name)


def _read_marker(workdir: Path) -> dict | None:
    marker = workdir / ".agent" / "result.yaml"
    if not marker.exists():
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(marker.read_text()))
    except Exception:
        return None


def _serialize_yaml(data: Any) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    buf = StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def run_implementer(
    *,
    repo,
    task_issue,
    task_body,
    goal_issue_number: int,
    goal_prose: str,
    sibling_artifacts: list[dict],
    base_branch: str,
    client: AgentClient,
    workdir: Path | None = None,
    decision_response: str | None = None,
) -> ImplementerResult:
    """Run Implementer in an isolated workdir."""
    workdir = workdir or Path(
        tempfile.mkdtemp(prefix=f"flow-impl-{task_body.task_id}-")
    )
    branch_name = f"task/{task_body.task_id}"

    print(f"[implementer] task_id={task_body.task_id} branch={branch_name}", flush=True)
    repo_path = workdir / "repo"

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
        local_repo = _clone_repo(clone_url, repo_path, branch=base_branch)
    except Exception as exc:
        return ImplementerResult(
            status="subprocess_error",
            branch_name=branch_name,
            blocker={"blocker_type": "clone_failed", "reason": str(exc)},
            workdir=workdir,
        )

    try:
        # Reuse existing branch if pushed already
        try:
            local_repo.git.fetch("origin", branch_name)
            local_repo.git.checkout(branch_name)
        except Exception:
            local_repo.git.checkout("-b", branch_name)
    except Exception:
        pass

    decision_block = ""
    if decision_response:
        decision_block = f"\n# Human decision (injected via /agent decide)\n\n{decision_response}\n"

    prompt = _PROMPT_TEMPLATE.format(
        cwd=str(repo_path),
        task_id=task_body.task_id,
        goal_issue=goal_issue_number,
        task_issue=task_issue.number,
        branch=branch_name,
        base=base_branch,
        task_spec_yaml=_serialize_yaml(task_body.spec.to_dict()),
        goal_prose=goal_prose[:4000] or "(no prose)",
        siblings_yaml=_serialize_yaml(sibling_artifacts) if sibling_artifacts else "[]",
    ) + decision_block

    # Host-side logs live OUTSIDE repo_path so they survive even if the
    # implementer wipes the repo workdir (e.g., `git clean -fdx`).
    log_dir = workdir / "host-logs" / "implementer"
    t0 = time.monotonic()
    cli_result = client.run(prompt=prompt, cwd=repo_path, log_dir=log_dir)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    emit_llm_call(
        role="implementer",
        goal=goal_issue_number,
        task_id=task_body.task_id,
        model=client.name,
        duration_ms=elapsed_ms,
        exit_status="ok" if cli_result.returncode == 0 else "non_zero",
    )

    marker = _read_marker(repo_path)
    if marker is None:
        if cli_result.returncode != 0:
            return ImplementerResult(
                status="subprocess_error",
                branch_name=branch_name,
                blocker={
                    "blocker_type": "subprocess_error",
                    "returncode": cli_result.returncode,
                    "stdout": (cli_result.stdout or "")[-2000:],
                    "stderr": (cli_result.stderr or "")[-2000:],
                },
                workdir=workdir,
                duration_ms=elapsed_ms,
            )
        return ImplementerResult(
            status="no_marker",
            branch_name=branch_name,
            blocker={"blocker_type": "no_result_marker"},
            workdir=workdir,
            duration_ms=elapsed_ms,
        )

    status = marker.get("status")
    if status == "blocked":
        return ImplementerResult(
            status="blocked",
            branch_name=branch_name,
            blocker=dict(marker.get("blocker") or {}),
            raw=marker,
            workdir=workdir,
            duration_ms=elapsed_ms,
        )

    if status != "done":
        return ImplementerResult(
            status="no_marker",
            branch_name=branch_name,
            blocker={"blocker_type": "unknown_status", "raw": marker},
            workdir=workdir,
            duration_ms=elapsed_ms,
        )

    # Done — push the branch (idempotent: agent may already have pushed)
    try:
        _push_branch(local_repo, branch_name)
    except Exception as exc:
        # Already pushed or push failure; check if PR already exists
        print(f"[implementer] push warn: {exc}", flush=True)

    # Find or create PR
    pr_number: int | None = None
    open_prs = list(repo.get_pulls(state="open", head=f"{repo.owner.login}:{branch_name}"))
    if open_prs:
        pr_number = open_prs[0].number
    else:
        artifacts = (marker.get("artifacts") or {})
        summary = str(artifacts.get("summary") or "").strip()
        spec = task_body.spec
        body_parts: list[str] = []
        body_parts.append("## Summary")
        body_parts.append("")
        body_parts.append(summary or spec.goal or task_issue.title)
        body_parts.append("")
        if spec.goal and (summary and summary != spec.goal):
            body_parts.append("## Task goal")
            body_parts.append("")
            body_parts.append(spec.goal.strip())
            body_parts.append("")
        qc = [str(c).strip() for c in (spec.quality_criteria or []) if str(c).strip()]
        if qc:
            body_parts.append("## Acceptance criteria")
            body_parts.append("")
            for c in qc:
                body_parts.append(f"- {c}")
            body_parts.append("")
        if task_body.goal_issue:
            body_parts.append(f"Parent goal: #{task_body.goal_issue}")
            body_parts.append("")
        body_parts.append(f"Closes #{task_issue.number}")
        body_parts.append("")
        body = "\n".join(body_parts)
        try:
            pr = repo.create_pull(
                title=f"[{task_body.task_id}] {task_body.spec.goal[:80] or task_issue.title}",
                body=body,
                head=branch_name,
                base=base_branch,
                draft=False,  # ready_for_review triggers reviewer; create non-draft
            )
            pr_number = pr.number
        except Exception as exc:
            return ImplementerResult(
                status="subprocess_error",
                branch_name=branch_name,
                blocker={"blocker_type": "pr_create_failed", "reason": str(exc)},
                workdir=workdir,
                duration_ms=elapsed_ms,
            )

    return ImplementerResult(
        status="done",
        pr_number=pr_number,
        branch_name=branch_name,
        summary=str((marker.get("artifacts") or {}).get("summary") or "").strip(),
        raw=marker,
        workdir=workdir,
        duration_ms=elapsed_ms,
    )
