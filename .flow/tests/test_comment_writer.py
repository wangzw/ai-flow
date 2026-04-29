from flow.comment_writer import build_ack_comment, build_needs_human_comment


def test_ack_accepted():
    msg = build_ack_comment(command="resume", accepted=True)
    assert "✅" in msg
    assert "/agent resume" in msg


def test_ack_rejected():
    msg = build_ack_comment(command="resume", accepted=False, reason="无效转换")
    assert "❌" in msg
    assert "无效转换" in msg


def test_needs_human_double_layer():
    msg = build_needs_human_comment(
        prose="some explanation",
        agent_state={"stage": "implementer", "blocker_type": "ask"},
        decision={"question": "X?", "options": [{"id": "A", "desc": "yes"}]},
    )
    assert "🛑" in msg
    assert "some explanation" in msg
    assert "```yaml" in msg
    assert "agent_state:" in msg
    assert "decision:" in msg
    assert "question:" in msg
    assert "/agent decide" in msg or "/agent resume" in msg


def test_plan_board_renders_table_and_yaml():
    from flow.comment_writer import PLAN_BOARD_MARKER, build_plan_board_comment

    body = build_plan_board_comment(
        iteration=2,
        last_run="2026-04-30T07:00:00+00:00",
        status="ok",
        summary="Working on adoption guide",
        desired_plan=[{"task_id": "T-a", "spec": {"goal": "do A"}, "deps": []}],
        children_progress=[
            {"task_id": "T-a", "issue": 42, "state": "agent-working",
             "title": "do A", "deps": []},
            {"task_id": "T-b", "issue": 43, "state": "agent-ready",
             "title": "do B", "deps": ["T-a"]},
        ],
    )
    # marker for upsert detection
    assert PLAN_BOARD_MARKER in body
    # header info
    assert "iteration **#2**" in body
    assert "status `ok`" in body
    # table rows for both tasks
    assert "`T-a`" in body and "#42" in body
    assert "`T-b`" in body and "#43" in body
    # deps rendered
    assert "T-a" in body  # dep listing
    # machine-readable yaml fence
    assert "```yaml" in body
    assert "iteration: 2" in body


def test_plan_board_handles_empty_children():
    from flow.comment_writer import build_plan_board_comment

    body = build_plan_board_comment(
        iteration=1, last_run=None, status="ok",
        summary="", desired_plan=[], children_progress=[],
    )
    assert "no child tasks yet" in body
    assert "```yaml" in body
