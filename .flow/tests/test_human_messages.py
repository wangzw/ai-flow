"""Tests for human-facing message builders.

Each builder must produce: a friendly headline, the specific data the
human needs to act on, and a "下一步" / next-steps section.
"""
from flow.human_messages import (
    failed_env_exhausted_comment,
    failed_env_retry_pending_comment,
    goal_complete_comment,
    planner_false_done_comment,
    planner_no_marker_comment,
    reviewer_arbitration_dispatched_comment,
    reviewer_max_iterations_comment,
    schedule_retry_dispatch_comment,
    task_cancelled_by_planner_comment,
    task_missing_frontmatter_comment,
)


def test_reviewer_max_iterations_lists_dims_with_reasons():
    msg = reviewer_max_iterations_comment(
        pr_number=42,
        iteration=5,
        failed_dimensions=["spec_compliance", "test_quality"],
        reasons={
            "spec_compliance": "README adds a manual clone flow not in spec",
            "test_quality": "新增公共 API 缺少单元测试",
        },
        history=[
            {"iteration": 1, "results": {"spec_compliance": "FAIL"}},
            {"iteration": 5, "results": {"spec_compliance": "FAIL"}},
        ],
    )
    # heading
    assert "Reviewer 已达最大迭代次数" in msg
    assert "PR #42" in msg
    # specific failure dims with reasons rendered as inline-code + bullet
    assert "`spec_compliance`" in msg
    assert "README adds a manual clone flow not in spec" in msg
    assert "`test_quality`" in msg
    assert "新增公共 API 缺少单元测试" in msg
    # actionable
    assert "下一步" in msg
    assert "/agent resume" in msg
    assert "/agent abort" in msg
    # history fenced (machine-readable)
    assert "<details>" in msg
    assert "```yaml" in msg


def test_reviewer_max_iterations_handles_missing_reasons():
    msg = reviewer_max_iterations_comment(
        pr_number=1,
        iteration=3,
        failed_dimensions=["spec_compliance"],
        reasons={},
        history=None,
    )
    assert "(no reason recorded)" in msg
    assert "<details>" not in msg  # no history block


def test_reviewer_arbitration_message_explains_what_planner_does():
    msg = reviewer_arbitration_dispatched_comment(
        task_issue_number=19,
        pr_number=20,
        iteration=2,
        failed_dimensions=["spec_compliance"],
        reasons={"spec_compliance": "scope drift"},
    )
    assert "⚖️" in msg
    assert "#19" in msg and "#20" in msg
    assert "Planner 仲裁" in msg or "请 Planner 仲裁" in msg
    assert "无需人工干预" in msg


def test_planner_no_marker_comment_includes_blocker_yaml():
    msg = planner_no_marker_comment(blocker={
        "blocker_type": "no_result_marker",
        "returncode": 1,
        "stderr": "boom",
    })
    assert "Planner 未产出结果" in msg
    assert "`no_result_marker`" in msg
    assert "退出码：`1`" in msg
    assert "<details>" in msg
    assert "stderr" in msg
    assert "/agent resume" in msg


def test_failed_env_messages_include_category_and_attempts():
    exhausted = failed_env_exhausted_comment(category="rate_limit", attempts=4)
    assert "`rate_limit`" in exhausted
    assert "**4**" in exhausted
    assert "needs-human" in exhausted
    assert "/agent resume" in exhausted

    pending = failed_env_retry_pending_comment(
        category="rate_limit", attempts=2, next_at="2026-04-30T08:00:00+00:00",
    )
    assert "自动重试" in pending
    assert "2026-04-30T08:00:00+00:00" in pending
    assert "无需人工介入" in pending


def test_planner_false_done_lists_non_terminal_issues():
    msg = planner_false_done_comment(non_terminal_issues=[10, 11, 12])
    assert "#10" in msg and "#11" in msg and "#12" in msg
    assert "needs-human" in msg


def test_goal_complete_includes_summary_when_provided():
    msg = goal_complete_comment(summary="Adoption guide merged in PR #20.")
    assert "✅" in msg
    assert "Adoption guide merged in PR #20." in msg

    msg2 = goal_complete_comment(summary=None)
    assert "Planner 报告所有子任务已完成。" in msg2


def test_task_cancelled_message_default_and_custom_reason():
    default = task_cancelled_by_planner_comment()
    assert "🚫" in default
    assert "agent-failed" in default

    custom = task_cancelled_by_planner_comment(reason="用户在评论中要求取消该任务。")
    assert "用户在评论中要求取消该任务。" in custom


def test_simple_messages_format_correctly():
    assert "缺少 frontmatter" in task_missing_frontmatter_comment()
    sched = schedule_retry_dispatch_comment(now_iso="2026-04-30T08:00:00+00:00")
    assert "⏰" in sched
    assert "2026-04-30T08:00:00+00:00" in sched


def test_no_message_advises_retry_from_needs_human():
    """`/agent retry` is only valid from `agent-working` per the state
    machine. All builders that move the issue into `needs-human` (or fire
    on a PR whose task is now `needs-human`) must NOT advise `/agent
    retry`, otherwise users hit ``❌ 当前状态 needs-human 不接受 /agent
    retry``.
    """
    needs_human_messages = [
        reviewer_max_iterations_comment(
            pr_number=1, iteration=5,
            failed_dimensions=["spec_compliance"], reasons={}, history=None,
        ),
        planner_no_marker_comment(blocker={"blocker_type": "no_result_marker"}),
        task_missing_frontmatter_comment(),
        failed_env_exhausted_comment(category="rate_limit", attempts=3),
    ]
    for msg in needs_human_messages:
        assert "/agent retry" not in msg, (
            f"message advises /agent retry but post-state is needs-human:\n{msg}"
        )
