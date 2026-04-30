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

_PROMPT_TEMPLATE = """You are the **Implementer agent** in the ai-flow framework. Your job is to
take ONE well-specified task, produce a working code change with tests, push
the branch, and open a pull request — then write a single marker file
recording what you did. The Reviewer (a separate agent) judges your output
against `quality_criteria`; the Coordinator (Python code) reads your marker
to decide what to do next.

You are running inside a fresh git clone. Your `cwd` is the project root.

================================================================
# Step 0 — Workdir layout (canonical)
================================================================

- Project root (your `cwd`):    `{cwd}`
- Branch (already checked out): `{branch}`
- Base branch:                   `{base}`
- **Marker file (your output)**: `{cwd}/.agent/result.yaml`

The `.agent/` directory does NOT exist yet — create it with `mkdir -p .agent`
before writing the marker. Always write to exactly that one path.

================================================================
# Step 1 — Read the task
================================================================

Task ID: `{task_id}`  
Goal Issue: `#{goal_issue}`  
Task Issue: `#{task_issue}`

## Task spec (the contract — Reviewer judges spec_compliance against this)

```yaml
{task_spec_yaml}
```

## Goal context (for orientation only — do NOT expand scope to satisfy it)

{goal_prose}

## Sibling artifacts (other tasks under the same goal — read-only context)

```yaml
{siblings_yaml}
```

================================================================
# Step 2 — Validate the spec BEFORE writing code
================================================================

Read `task.spec.quality_criteria` carefully. For EACH item, ask: "Could a
reviewer verify this is satisfied by reading the diff and running tests?"

If the answer is **no** for any item (vague, contradictory, references
unavailable resources, etc.), STOP. Do NOT start coding. Instead, emit a
`status: blocked` marker (see Step 7 shape B) with `blocker.type:
spec_ambiguity` and a precise question. The Planner will tighten the spec
and re-dispatch — that is the correct path forward.

================================================================
# Step 3 — Implement the change (TDD-friendly)
================================================================

1. **Explore the codebase first.** Read existing patterns, tests, and
   conventions in the relevant module(s). Match style.
2. **Write or extend tests** that cover EACH `quality_criteria` item.
   Tests must contain real assertions — empty `assert True` or tautological
   tests will be flagged by the `test_quality` reviewer.
3. **Implement the production code** to make the tests pass.
4. **Run the project's test/lint commands** (e.g. `pytest`, `ruff check`,
   `npm test`, `cargo test`). Iterate until everything is green.
5. **Add code comments for non-obvious WHY**: constraints, workarounds,
   invariants the diff doesn't make obvious. The Reviewer reads ONLY the
   diff, tests, and code-comments — NOT your PR description, commit
   messages, or self-summary. So anything important must live in the code.

================================================================
# Step 4 — Commit
================================================================

Use Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, …).
Stage everything you changed:

```sh
git add -A
git commit -m "<conventional commit message>"
```

DO NOT include reviewer-targeted prose in the commit message — it is for
humans/release-tooling only.

================================================================
# Step 5 — Push the branch
================================================================

```sh
git push --set-upstream origin {branch}
```

If push fails because the branch already exists upstream, just `git push`
(no `--set-upstream`) — the framework already created the remote ref.

================================================================
# Step 6 — Open a pull request
================================================================

Use the `gh` CLI (already authenticated via the runner's `GH_TOKEN`):

```sh
gh pr create \\
  --base {base} \\
  --head {branch} \\
  --title "[{task_id}] <short imperative description>" \\
  --body "$(cat <<'EOF'
## Summary
<1–3 sentences: what changed, at a high level>

## Motivation / Context
<why this change is needed; reference goal #{goal_issue}>

## Changes
- <bullet 1>
- <bullet 2>

## Testing
<commands you ran and what they verified>

Closes #{task_issue}
EOF
)"
```

If a PR for this branch already exists (e.g. you are re-running on a
previously-pushed branch), `gh pr create` will fail; that is fine — proceed
to Step 7. Do not delete or recreate the PR.

================================================================
# Step 7 — Write the marker file (REQUIRED, last step)
================================================================

```sh
mkdir -p .agent
```

## Shape A — Success (`status: done`):

```yaml
schema_version: 1
status: done
artifacts:
  branch: {branch}
  pr_opened: true
  summary: |
    One-paragraph self-summary for the Planner. Mention the key files
    touched and which quality_criteria items each test covers.
```

## Shape B — Cannot proceed (`status: blocked`):

```yaml
schema_version: 1
status: blocked
blocker:
  type: spec_ambiguity   # or: cross_module_conflict | dep_unmet | tool_error | model_error | ask
  message: "<one-line description>"
  details:
    <free-form structured context>
  question: "<concrete question; only when type=ask>"
  options:
    - {{id: A, desc: "..."}}
```

================================================================
# Hard rules (violations create review-loop failures)
================================================================

1. **Channel discipline.** Reviewer reads diff/tests/code-comments only. Put
   the WHY for non-obvious choices in code comments, NOT in the PR body or
   commit message.
2. **Stay in scope.** Do NOT touch files outside what the task spec implies.
   Do NOT "improve" unrelated code "while you're there".
3. **Write the marker.** Missing `{cwd}/.agent/result.yaml` is treated as a
   failed environment by the Coordinator and forces the goal into
   `needs-human`. If you genuinely cannot complete, emit `blocked`.
4. **Tests are mandatory.** Every quality_criterion needs corresponding
   test coverage in the same PR. Otherwise `test_quality` will FAIL.
5. **No interactive commands.** You are running non-interactively. Do not
   wait for user input; if a tool prompts, pass `--yes` / `-y` flags.
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
