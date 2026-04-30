"""flow CLI (spec §13.2)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import click

from flow import __version__
from flow.clients.github import ALL_FLOW_LABELS

FLOW_PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_ROOT = Path(__file__).parent / "bootstrap"


def _copy_file(src: Path, dst: Path, force: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not force:
        click.echo(f"skip (exists): {dst}")
        return
    shutil.copy2(src, dst)
    click.echo(f"wrote {dst}")


def _copy_tree(src_root: Path, dst_root: Path, force: bool) -> None:
    for src in src_root.rglob("*"):
        rel = src.relative_to(src_root)
        if "__pycache__" in rel.parts:
            continue
        dst = dst_root / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        _copy_file(src, dst, force)


@click.group()
@click.version_option(__version__)
def main() -> None:
    """ai-flow command-line interface."""


@main.command()
@click.option("--target", type=click.Path(file_okay=False), default=".",
              help="Target project root (default: cwd).")
@click.option("--force", is_flag=True, help="Overwrite existing files.")
def init(target: str, force: bool) -> None:
    """Bootstrap .flow/ + .github/workflows in TARGET (spec §13.3)."""
    target_root = Path(target).resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    # The generated workflows install `./.flow` and execute `python -m flow.*`,
    # so `flow init` must vendor the runtime package into the target repo too.
    runtime_root = target_root / ".flow"
    _copy_file(FLOW_PROJECT_ROOT / "pyproject.toml", runtime_root / "pyproject.toml", force)
    _copy_tree(FLOW_PROJECT_ROOT / "src", runtime_root / "src", force)

    # 1) Copy workflows
    workflows_src = BOOTSTRAP_ROOT / "workflows"
    workflows_dst = target_root / ".github" / "workflows"
    workflows_dst.mkdir(parents=True, exist_ok=True)
    for fp in workflows_src.glob("*.yml"):
        _copy_file(fp, workflows_dst / fp.name, force)

    # 2) Copy issue template
    it_src = BOOTSTRAP_ROOT / "issue_template" / "goal.md"
    it_dst = target_root / ".github" / "ISSUE_TEMPLATE" / "goal.md"
    _copy_file(it_src, it_dst, force)

    # 3) Default config
    cfg_src = BOOTSTRAP_ROOT / "config.yml"
    cfg_dst = target_root / ".flow" / "config.yml"
    _copy_file(cfg_src, cfg_dst, force)

    # 4) Prompts (informational only — actual prompts are inlined in code)
    prompts_src = BOOTSTRAP_ROOT / "prompts"
    if prompts_src.exists():
        prompts_dst = target_root / ".flow" / "prompts"
        prompts_dst.mkdir(parents=True, exist_ok=True)
        for fp in prompts_src.glob("*.md"):
            _copy_file(fp, prompts_dst / fp.name, force)

    click.echo("\n✅ flow init complete. Next:")
    click.echo("  1. flow apply-labels --repo <owner/repo>")
    click.echo("  2. flow doctor --repo <owner/repo>")


@main.command(name="apply-labels")
@click.option("--repo", required=True, help="GitHub repo (owner/name)")
def apply_labels(repo: str) -> None:
    """Create the 7 ai-flow labels in REPO."""
    from github import Github

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("FLOW_GIT_TOKEN")
    if not token:
        raise click.ClickException("GITHUB_TOKEN or FLOW_GIT_TOKEN required")
    gh = Github(token)
    r = gh.get_repo(repo)
    existing = {lbl.name for lbl in r.get_labels()}

    color_map = {
        "agent-ready":   "0e8a16",
        "agent-working": "fbca04",
        "needs-human":   "d93f0b",
        "agent-done":    "5319e7",
        "agent-failed":  "b60205",
        "type:goal":     "1d76db",
        "type:task":     "5319e7",
        "merge-queued":  "0052cc",
    }
    for name in ALL_FLOW_LABELS:
        if name in existing:
            click.echo(f"  exists: {name}")
            continue
        r.create_label(name=name, color=color_map.get(name, "ededed"))
        click.echo(f"  created: {name}")


@main.command()
@click.option("--repo", required=True, help="GitHub repo (owner/name)")
def doctor(repo: str) -> None:
    """Verify environment, secrets, labels, and runner workflows (spec §13.2)."""
    ok = True

    def check(desc: str, cond: bool, hint: str = "") -> None:
        nonlocal ok
        sym = "✅" if cond else "❌"
        click.echo(f"  {sym} {desc}{' — ' + hint if not cond and hint else ''}")
        if not cond:
            ok = False

    # 1. CLI tools
    check("git available", shutil.which("git") is not None)
    check("copilot CLI available",
          shutil.which("copilot") is not None,
          "install: gh extension install github/gh-copilot")

    # 2. GitHub auth
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("FLOW_GIT_TOKEN")
    check("GITHUB_TOKEN/FLOW_GIT_TOKEN env set", token is not None)

    if token:
        from github import Github

        gh = Github(token)
        try:
            r = gh.get_repo(repo)
            check(f"repo accessible: {repo}", True)
            existing = {lbl.name for lbl in r.get_labels()}
            for name in ALL_FLOW_LABELS:
                check(f"label {name} present", name in existing,
                      "run: flow apply-labels")
            wf_dir = (".github/workflows")
            try:
                contents = r.get_contents(wf_dir)
                wf_files = {item.name for item in contents if item.name.startswith("flow-")}
                for required in ("flow-issue.yml", "flow-comment.yml",
                                 "flow-pr-ready.yml", "flow-merge-queue.yml"):
                    check(f"workflow {required} present", required in wf_files)
            except Exception as exc:
                check("workflows directory accessible", False, str(exc))
        except Exception as exc:
            check(f"repo accessible: {repo}", False, str(exc))

    # 3. Local config
    cfg_path = Path(".flow/config.yml")
    check(".flow/config.yml present", cfg_path.exists(),
          "run: flow init")

    sys.exit(0 if ok else 1)


@main.command()
@click.option("--repo", required=True)
@click.option("--goal", type=int, help="Goal Issue number; omit for all goals.")
def status(repo: str, goal: int | None) -> None:
    """Display the live state of one or all goal trees."""
    from github import Github

    from flow.manifest import GoalBody

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("FLOW_GIT_TOKEN")
    if not token:
        raise click.ClickException("GITHUB_TOKEN or FLOW_GIT_TOKEN required")
    r = Github(token).get_repo(repo)

    issues = [r.get_issue(goal)] if goal else r.get_issues(state="all", labels=["type:goal"])
    for issue in issues:
        click.echo(f"\n#{issue.number} [{issue.state}] {issue.title}")
        labels = [lbl.name for lbl in issue.labels]
        click.echo(f"  labels: {labels}")
        gb = GoalBody.parse(issue.body or "")
        click.echo(f"  manifest: {len(gb.manifest)} task(s)")
        for entry in gb.manifest:
            click.echo(f"    - {entry.task_id} #{entry.issue} [{entry.state}] deps={entry.deps}")


@main.command()
@click.argument("command", type=click.Choice(
    ["issue-labeled", "comment-created", "pr-ready", "merge-queue", "schedule"]))
def dispatch(command: str) -> None:
    """Invoke the coordinator with COMMAND (delegates to flow.coordinator)."""
    from flow.coordinator import _COMMANDS

    sys.exit(_COMMANDS[command]())


@main.group()
def report() -> None:
    """Reporting commands."""


@report.command()
@click.option("--metrics-file", type=click.Path(),
              help="JSONL metrics file (default: $FLOW_METRICS_FILE)")
def cost(metrics_file: str | None) -> None:
    """Aggregate llm_call events into per-goal cost report (spec §14.4)."""
    import json
    from collections import defaultdict

    src = metrics_file or os.environ.get("FLOW_METRICS_FILE")
    if not src or not Path(src).exists():
        raise click.ClickException(
            "set --metrics-file or FLOW_METRICS_FILE to a JSONL log path")
    by_goal: dict = defaultdict(lambda: {"calls": 0, "ms": 0, "by_role": defaultdict(int)})
    with open(src) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("event") != "llm_call":
                continue
            fields = rec.get("fields") or {}
            goal = fields.get("goal") or "n/a"
            by_goal[goal]["calls"] += 1
            by_goal[goal]["ms"] += int(fields.get("duration_ms") or 0)
            by_goal[goal]["by_role"][fields.get("role") or "?"] += 1

    click.echo(f"{'goal':>10}  {'calls':>6}  {'minutes':>8}  by_role")
    for goal, agg in sorted(by_goal.items(), key=lambda kv: str(kv[0])):
        roles = ", ".join(f"{r}={n}" for r, n in agg["by_role"].items())
        click.echo(f"{str(goal):>10}  {agg['calls']:>6}  {agg['ms']/60000:>8.1f}  {roles}")


if __name__ == "__main__":
    main()
