"""Double-layer needs-human comment template (spec §10.2)."""

from io import StringIO

from ruamel.yaml import YAML

_TEMPLATE = """## 🛑 需要人类决策

{prose}

```yaml
{yaml_block}```

{resume_instruction}
"""

_DEFAULT_RESUME = (
    "请评论 `/agent decide <id>` 选择，或写自定义答案后 `/agent resume`，或 `/agent abort` 终止。"
)


def build_needs_human_comment(
    *,
    prose: str,
    agent_state: dict,
    decision: dict,
    resume_instruction: str = _DEFAULT_RESUME,
) -> str:
    """Build a double-layer needs-human comment per spec §10.2."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)

    payload = {
        "agent_state": agent_state,
        "decision": decision,
        "resume_instruction": resume_instruction,
    }
    buf = StringIO()
    yaml.dump(payload, buf)

    return _TEMPLATE.format(
        prose=prose, yaml_block=buf.getvalue(), resume_instruction=resume_instruction
    )


def build_ack_comment(*, command: str, accepted: bool, reason: str = "") -> str:
    """Bot acknowledgment per spec §10.4 (mandatory after any /agent command)."""
    if accepted:
        return f"✅ 收到 `/agent {command}`，已执行。"
    return f"❌ 拒绝 `/agent {command}`：{reason}"


# Marker used by the upsert helper to tell whether an existing comment is
# the one we manage (so we update it instead of creating duplicates). Kept
# inside an HTML comment so it doesn't render in the GitHub UI.
PLAN_BOARD_MARKER = "<!-- flow:plan-board -->"


def build_plan_board_comment(
    *,
    iteration: int,
    last_run: str | None,
    status: str,
    summary: str,
    desired_plan: list[dict],
    children_progress: list[dict],
) -> str:
    """Render the goal-issue plan/progress board.

    Layout:
    - Short prose header (humans skim this)
    - A markdown table of tasks (humans read this)
    - A fenced YAML block with the structured payload (machines/automation
      can parse it; the fence keeps it out of the way for humans)

    `children_progress` items: {task_id, issue, state, title, deps}
    `desired_plan` items: items from PlannerResult.desired_plan
    """
    from io import StringIO

    from ruamel.yaml import YAML

    parts: list[str] = [PLAN_BOARD_MARKER, "", "## 🗺️ 计划与进度"]

    header = f"Planner iteration **#{iteration}** · status `{status}`"
    if last_run:
        header += f" · last run `{last_run}`"
    parts.append(header)
    parts.append("")

    if summary:
        parts.append(summary)
        parts.append("")

    if children_progress:
        parts.append("| Task | Issue | State | Goal | Deps |")
        parts.append("| --- | --- | --- | --- | --- |")
        for c in children_progress:
            deps = ", ".join(c.get("deps") or []) or "—"
            title = (c.get("title") or "").replace("|", "\\|")
            parts.append(
                f"| `{c.get('task_id', '')}` "
                f"| #{c.get('issue', '')} "
                f"| `{c.get('state', '')}` "
                f"| {title} "
                f"| {deps} |"
            )
        parts.append("")
    else:
        parts.append("_(no child tasks yet)_")
        parts.append("")

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    payload = {
        "iteration": iteration,
        "last_run": last_run,
        "status": status,
        "desired_plan": desired_plan,
        "children": children_progress,
    }
    buf = StringIO()
    yaml.dump(payload, buf)
    parts.append("<details><summary>结构化数据 (machine-readable)</summary>")
    parts.append("")
    parts.append("```yaml")
    parts.append(buf.getvalue().rstrip())
    parts.append("```")
    parts.append("")
    parts.append("</details>")

    return "\n".join(parts) + "\n"
