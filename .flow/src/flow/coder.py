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
from flow.prompts import load_prompt

_PROMPT_TEMPLATE = load_prompt("coder")


@dataclass
class ImplementerResult:
    status: str  # "done" | "blocked" | "no_marker" | "subprocess_error" | "pr_create_failed"
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
    push_warning: str | None = None
    try:
        _push_branch(local_repo, branch_name)
    except Exception as exc:
        # Already pushed or push failure; check if PR already exists
        push_warning = str(exc)
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
                status="pr_create_failed",
                branch_name=branch_name,
                blocker={
                    "blocker_type": "pr_create_failed",
                    "reason": str(exc),
                    "push_warning": push_warning,
                },
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
