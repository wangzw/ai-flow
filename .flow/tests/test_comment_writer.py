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
