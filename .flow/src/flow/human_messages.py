"""Builders for human-facing GitHub comments.

Goal: every comment the framework posts to a human must be:

* **Friendly to read** — emoji-prefixed heading, short prose, structured
  sections; never a raw dict dump.
* **Specific** — name the failing dimension, the file, the iteration, the
  retry budget left. Include the data the human needs to act.
* **Actionable** — end with a "下一步" section that lists the concrete
  commands the human can run (`/agent resume`, `/agent abort`, …) or the
  link they should open.
* **Two-layer** — when the message also carries machine-readable state,
  wrap that payload in a fenced ```yaml block so scripts can parse it
  while humans skim.

All builders return a Markdown string. Keep them small and compositional —
the call sites pass already-collected context, builders just format.
"""

from __future__ import annotations

from io import StringIO
from typing import Any

from ruamel.yaml import YAML


def _yaml_block(payload: dict) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    buf = StringIO()
    yaml.dump(payload, buf)
    return "```yaml\n" + buf.getvalue().rstrip() + "\n```"


def _details(summary: str, body: str) -> str:
    return f"<details><summary>{summary}</summary>\n\n{body}\n\n</details>"


def _next_steps(items: list[str]) -> str:
    if not items:
        return ""
    lines = ["### 👉 下一步"]
    for it in items:
        lines.append(f"- {it}")
    return "\n".join(lines)


def reviewer_max_iterations_comment(
    *,
    pr_number: int,
    iteration: int,
    failed_dimensions: list[str],
    reasons: dict[str, str],
    history: list[dict] | None = None,
) -> str:
    """Reviewer hit max iterations on a task — needs human intervention."""
    parts: list[str] = [
        f"## ❌ Reviewer 已达最大迭代次数（{iteration}/{iteration}）",
        "",
        f"PR #{pr_number} 在 {iteration} 轮 Implementer ↔ Reviewer 循环后仍未通过质量门槛，"
        "已切换为 `needs-human`，等待人工介入。",
        "",
        "### 失败维度",
    ]
    if failed_dimensions:
        for d in failed_dimensions:
            reason = (reasons or {}).get(d, "(no reason recorded)")
            parts.append(f"- **`{d}`** — {reason}")
    else:
        parts.append("- _(none recorded)_")
    parts.append("")

    if history:
        parts.append(_details(
            f"迭代历史（{len(history)} 轮）",
            _yaml_block({"history": history}),
        ))
        parts.append("")

    parts.append(_next_steps([
        f"打开 PR #{pr_number}，结合上面的失败原因决定下一步。",
        "若希望沿当前方向再试一轮，评论 `/agent resume`"
        "（从 `needs-human` 重新进入 `agent-working`）。",
        "若需要换思路，编辑该 task issue 的 spec（goal / quality_criteria）后"
        "再评论 `/agent resume`。",
        "若任务无法继续，评论 `/agent abort` 终止；或评论 `/agent escalate` 把问题上抛到 Goal。",
    ]))
    return "\n".join(parts) + "\n"


def reviewer_arbitration_dispatched_comment(
    *,
    task_issue_number: int,
    pr_number: int,
    iteration: int,
    failed_dimensions: list[str],
    reasons: dict[str, str],
) -> str:
    """Posted on the goal issue when Reviewer is stuck and Planner is asked to arbitrate."""
    parts = [
        "## ⚖️ Reviewer 死循环 — 已请 Planner 仲裁",
        "",
        f"子任务 #{task_issue_number} 的 PR #{pr_number} 在第 {iteration} 轮仍未通过 Reviewer。"
        "已将该 Goal 重新置为 `agent-working`，Planner 将基于失败原因"
        "决定是否调整 spec / 拆分任务。",
        "",
        "### 失败维度",
    ]
    if failed_dimensions:
        for d in failed_dimensions:
            reason = (reasons or {}).get(d, "(no reason)")
            parts.append(f"- **`{d}`** — {reason}")
    else:
        parts.append("- _(none recorded)_")
    parts.append("")
    parts.append(
        "_无需人工干预 — 若 Planner 仲裁后仍失败 (超过 `max_arbitrations`)，"
        "会再次切换为 `needs-human`。_"
    )
    return "\n".join(parts) + "\n"


def planner_no_marker_comment(*, blocker: dict[str, Any]) -> str:
    """Planner subprocess didn't produce a valid result.yaml — surface context."""
    btype = blocker.get("blocker_type", "unknown")

    if btype == "invalid_marker":
        attempts = blocker.get("attempts")
        attempts_txt = f"（已自动重试 {attempts} 次）" if attempts else ""
        parts = [
            "## ❌ Planner 输出未通过格式校验",
            "",
            f"Planner 写出了 `.flow/result.yaml`，但所有 {attempts or '?'} 次"
            "尝试都未通过 Python 端的严格 schema 校验"
            f"{attempts_txt}。已将本 issue 切换为 `needs-human`。",
            "",
        ]
        errors = blocker.get("errors") or []
        if errors:
            parts.append("**校验错误（最后一次尝试）：**")
            for e in errors:
                parts.append(f"- {e}")
            parts.append("")
        marker = blocker.get("marker")
        if marker:
            parts.append(_details("最后一次（被拒绝的）result.yaml",
                                  _yaml_block(marker)))
            parts.append("")
        parts.append(_next_steps([
            "查看 workflow artifact 里 `host-logs/planner/attempt-*/` "
            "下的 stdout/stderr 日志，确认 Copilot 实际输出。",
            "若是 Planner prompt 引导不足，提交 PR 改进 "
            "`.flow/src/flow/planner.py::_PROMPT_TEMPLATE`。",
            "排除问题后评论 `/agent resume` 重新触发 Planner，"
            "或 `/agent replan <hint>` 提供更具体的指引。",
        ]))
        return "\n".join(parts) + "\n"

    parts = [
        "## ❌ Planner 未产出结果",
        "",
        f"Planner 子进程未能写出 `.flow/result.yaml`（blocker_type=`{btype}`）。"
        "已将本 issue 切换为 `needs-human`。",
        "",
    ]

    rc = blocker.get("returncode")
    if rc is not None:
        parts.append(f"- 退出码：`{rc}`")
    if "reason" in blocker:
        parts.append(f"- 原因：{blocker['reason']}")
    parts.append("")

    detail_payload = {k: v for k, v in blocker.items()
                      if k not in {"blocker_type", "returncode", "reason"}}
    if detail_payload:
        parts.append(_details("Planner 子进程输出（截断）",
                              _yaml_block(detail_payload)))
        parts.append("")

    parts.append(_next_steps([
        "查看本次 workflow run 的 `flow-issue-*` artifact，"
        "里面有 `host-logs/planner/copilot-stdout.log`。",
        "排除问题后评论 `/agent resume`（从 `needs-human` 进入 `agent-working`）重新触发 Planner。",
        "若是 Planner 行为异常，评论 `/agent escalate` 上报维护者，或 `/agent abort` 终止 Goal。",
    ]))
    return "\n".join(parts) + "\n"


def task_missing_frontmatter_comment() -> str:
    return (
        "## ❌ Task body 缺少 frontmatter\n\n"
        "该 task issue 的 body 解析不出 `task_id`，无法进入 Implementer 流水线。"
        "已切换为 `needs-human`。\n\n"
        "### 👉 下一步（任选其一）\n"
        "- **手动补齐**：参考其它 task issue 的 frontmatter 结构，"
        "把 `task_id` 等字段写回本 issue 的 body，然后在本 issue 评论 `/agent resume`。\n"
        "- **由 Planner 重新生成**：在 **Goal issue** 上评论 "
        "`/agent replan <hint>`（hint 简述要修复什么），"
        "Planner 会重新规划包括本任务在内的整个 plan。"
        "Goal 处于 `agent-ready` / `agent-working` / `needs-human` 任一状态都可以接受。\n"
    )


def failed_env_exhausted_comment(*, category: str, attempts: int) -> str:
    return (
        "## ⛔ 环境性失败已耗尽重试预算\n\n"
        f"分类：**`{category}`**　已尝试：**{attempts}** 次。\n"
        "已切换为 `needs-human` 等待人工排查环境问题（quota、网络、token 权限等）。\n\n"
        "### 👉 下一步\n"
        f"- 参考 workflow run 日志确认 `{category}` 类失败的根因。\n"
        "- 修复环境后评论 `/agent resume` 重置计数并从 `needs-human` 重新调度。\n"
        "- 若问题暂时无法解决，评论 `/agent abort` 终止任务。\n"
    )


def failed_env_retry_pending_comment(
    *, category: str, attempts: int, next_at: str
) -> str:
    return (
        "## ⏳ 环境性失败 — 已计划自动重试\n\n"
        f"分类：**`{category}`**　已尝试：**{attempts}** 次。\n"
        f"将于 `{next_at}` 自动重新调度。\n\n"
        "_无需人工介入 — 若超过预算会自动升级为 `needs-human`。_\n"
    )


def schedule_retry_dispatch_comment(*, now_iso: str) -> str:
    return (
        f"## ⏰ failed-env 自动重试触发\n\n"
        f"调度时间：`{now_iso}`。已切换标签触发 Implementer 重新运行。\n"
    )


def planner_false_done_comment(*, non_terminal_issues: list[int]) -> str:
    issue_list = ", ".join(f"#{n}" for n in non_terminal_issues) or "(none)"
    return (
        "## ❌ Planner 声称 `done` 但仍有未完成任务\n\n"
        f"以下子任务尚未进入终态：{issue_list}。\n"
        "已强制切换为 `needs-human` 防止误关闭。\n\n"
        "### 👉 下一步\n"
        "- 检查上述 task issue 的状态标签，决定是否继续推进。\n"
        "- 若确实希望关闭 Goal，先把这些任务置为终态"
        "（`agent-done` / `agent-failed` / `agent-cancelled`），"
        "再评论 `/agent resume`。\n"
    )


def goal_complete_comment(*, summary: str | None) -> str:
    body = summary.strip() if summary else "Planner 报告所有子任务已完成。"
    return (
        "## ✅ Goal 已完成\n\n"
        f"{body}\n\n"
        "_本 issue 将被标记为 `agent-done` 并关闭。如需追加后续工作，请新建 Goal issue。_\n"
    )


def implementer_no_marker_comment(
    *, blocker_type: str, raw: dict | None = None,
    stdout_tail: str = "", stderr_tail: str = "",
) -> str:
    """A2/A3: Implementer 没有产出有效 result.yaml（区别于环境性失败）。"""
    head = (
        "## ❌ Implementer 未产出有效 result.yaml\n\n"
        f"分类：**`{blocker_type}`**。这通常**不是环境问题**，而是模型未能按约定写入 "
        "`.agent/result.yaml`（status 为 `done` 或 `blocked`）。盲目重试会浪费配额，"
        "已直接切换为 `needs-human` 等待排查。\n\n"
    )
    debug_parts: list[str] = []
    if raw:
        debug_parts.append("**收到的（无效）marker：**\n\n" + _yaml_block(raw))
    if stdout_tail.strip():
        debug_parts.append(
            "**stdout 末尾：**\n\n```\n" + stdout_tail.strip()[-1500:] + "\n```"
        )
    if stderr_tail.strip():
        debug_parts.append(
            "**stderr 末尾：**\n\n```\n" + stderr_tail.strip()[-1500:] + "\n```"
        )
    debug = ("\n\n".join(debug_parts) + "\n\n") if debug_parts else ""
    next_steps = _next_steps([
        "查看上述输出与 `host-logs/implementer/` 里的完整日志，确认根因。",
        "若是 spec 不清晰：在 **Goal issue** 上 `/agent replan <hint>` 重新规划。",
        "若环境/Token 等已修复并希望直接重试：评论 `/agent resume`。",
        "若任务无法执行：评论 `/agent abort` 终止。",
    ])
    return head + debug + next_steps + "\n"


def implementer_pr_create_failed_comment(*, reason: str, branch: str) -> str:
    """A5: PR 创建失败（多半是 PR 已存在 / branch protection / 冲突等非自愈问题）。"""
    return (
        "## ❌ PR 创建失败\n\n"
        f"分支：`{branch}`\n\n"
        f"GitHub 返回：\n\n```\n{reason.strip()[:1500]}\n```\n\n"
        "这通常**不是环境性故障**，常见原因：\n"
        "- 该分支已存在打开的 PR（请检查 `pulls?head=...`）。\n"
        "- 目标分支启用了 branch protection 而当前 actor 缺少权限。\n"
        "- head 与 base 之间没有差异，或仓库设置不允许从该分支创建 PR。\n\n"
        "已切换为 `needs-human`，避免无意义重试。\n\n"
        + _next_steps([
            "排查上述原因，必要时手工创建 PR 后评论 `/agent resume`。",
            "若需要重新规划：在 Goal issue 上 `/agent replan <hint>`。",
            "若放弃此任务：评论 `/agent abort`。",
        ])
        + "\n"
    )


def review_clone_failed_comment(*, branch: str, reason: str) -> str:
    """B6: Reviewer 阶段克隆失败 — 当作 infra 类失败提示，调度自动重试。"""
    return (
        "## ⚠️ Reviewer 无法克隆 PR 分支\n\n"
        f"分支：`{branch}`\n\n"
        f"错误：\n\n```\n{reason.strip()[:1500]}\n```\n\n"
        "Reviewer 跳过本轮评审。已尝试将关联 task 切换为 `needs-human`，"
        "请在网络/Token 修复后重新触发评审（评论 `/agent resume`）。\n"
    )


def merge_queue_clone_failed_comment(*, branch: str, reason: str) -> str:
    """C3: Merge queue 阶段克隆失败 — 静默踢出会让用户困惑，给出明确解释。"""
    return (
        "## ⚠️ Merge queue 无法克隆 PR 分支\n\n"
        f"分支：`{branch}`\n\n"
        f"错误：\n\n```\n{reason.strip()[:1500]}\n```\n\n"
        "已从合并队列移除（去掉 `merge-queued` 标签）。请在排查后重新加上 "
        "`merge-queued` 标签或评论 `/agent resume` 重新进入队列。\n"
    )


def merge_failed_comment(*, reason: str, classification: str) -> str:
    """C4: head.merge() 抛异常 — 分类后给出修复建议。"""
    hints: dict[str, str] = {
        "conflict": (
            "PR 与 base 分支存在冲突，需要 rebase 后再次评审。"
            "Implementer 将被重新调度以解决冲突。"
        ),
        "required_check": (
            "目标分支的 branch protection 要求的 status check 缺失或未通过。"
            "请在 GitHub Settings → Branches 中检查保护规则，或等待 CI 完成。"
        ),
        "stale": (
            "PR 已不在最新状态（base 分支推进了），需要 rebase。"
            "Implementer 将被重新调度。"
        ),
        "other": "未识别的合并错误，请查看下方原始错误信息。",
    }
    hint = hints.get(classification, hints["other"])
    return (
        "## ❌ 合并失败\n\n"
        f"分类：**`{classification}`**\n\n"
        f"{hint}\n\n"
        f"GitHub API 错误：\n\n```\n{reason.strip()[:1500]}\n```\n\n"
        "已从合并队列移除（去掉 `merge-queued` 标签），关联 task 切回 "
        "`agent-working` 等待新一轮 Implementer 处理。\n\n"
        + _next_steps([
            "若是冲突 / stale：等待自动重新调度的 Implementer 完成 rebase。",
            "若是 branch protection：人工调整保护规则后评论 `/agent resume`。",
            "若放弃合并：手动关闭此 PR 并评论 `/agent abort` 终止任务。",
        ])
        + "\n"
    )


def goal_aborted_cascade_comment(
    *, goal: int, closed_prs: list[int] | None = None,
) -> str:
    pr_line = ""
    if closed_prs:
        prs = ", ".join(f"#{n}" for n in closed_prs)
        pr_line = f"已关联关闭的 PR：{prs}\n\n"
    return (
        "## 🚫 父 Goal 已被中止 — 任务联动取消\n\n"
        f"父 Goal **#{goal}** 收到 `/agent abort`，因此本任务一并终止，"
        "状态切换为 `agent-failed` 并关闭。\n\n"
        f"{pr_line}"
        "_如需重新推进相关工作，请新建 Goal issue。_\n"
    )


def goal_abort_summary_comment(
    *, cancelled_tasks: list[int], closed_prs: list[int],
) -> str:
    head = "## 🛑 Goal 已中止 — 联动清理完成\n\n"
    if not cancelled_tasks and not closed_prs:
        return head + "未发现需要清理的子任务或 PR。Goal 已切换为 `agent-failed`。\n"
    parts = [head]
    if cancelled_tasks:
        ts = ", ".join(f"#{n}" for n in cancelled_tasks)
        parts.append(f"- 已取消子任务：{ts}\n")
    if closed_prs:
        ps = ", ".join(f"#{n}" for n in closed_prs)
        parts.append(f"- 已关闭关联 PR：{ps}\n")
    parts.append(
        "\nGoal 自身已切换为 `agent-failed` 并关闭。"
        "如需重新推进，请新建 Goal issue。\n"
    )
    return "".join(parts)


def task_aborted_pr_closed_comment(*, pr: int) -> str:
    return (
        "## 🚫 任务中止 — 关联 PR 已关闭\n\n"
        f"由于本任务收到 `/agent abort`，关联 PR **#{pr}** 已被自动关闭。\n"
        "如需恢复工作，请新建任务并重新规划。\n"
    )


def task_cancelled_by_planner_comment(*, reason: str | None = None) -> str:
    why = reason or "Planner 在新一轮 reconcile 中将该任务移出了 desired plan。"
    return (
        "## 🚫 任务被 Planner 取消\n\n"
        f"{why}\n\n"
        "状态已切换为 `agent-failed`。如有疑问，可在 **Goal issue** 上评论 "
        "`/agent replan <hint>` 重新规划（Goal 在任意非终态都可接受）。\n"
    )
