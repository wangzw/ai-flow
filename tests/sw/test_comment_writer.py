from sw.comment_parser import extract_yaml_block
from sw.comment_writer import build_needs_human_comment


def test_build_comment_contains_natural_language():
    comment = build_needs_human_comment(
        prose="AC 中没有说软删除是否保留登录历史。",
        agent_state={"stage": "coder", "blocker_type": "ac_ambiguity", "progress": "model 完成"},
        decision={
            "question": "保留登录历史？",
            "options": [{"id": "keep", "desc": "保留"}, {"id": "purge", "desc": "删除"}],
            "custom_allowed": True,
        },
    )
    assert "AC 中没有说软删除是否保留登录历史。" in comment
    assert "🛑" in comment


def test_build_comment_contains_resume_instruction():
    comment = build_needs_human_comment(
        prose="x", agent_state={}, decision={"question": "q", "options": []}
    )
    assert "/agent resume" in comment


def test_built_comment_round_trips_through_parser():
    """Critical: writer + parser are inverse — agent can read its own state on resume."""
    state = {"stage": "coder", "blocker_type": "ac_ambiguity", "progress": "step 3 done"}
    decision = {
        "question": "Q?",
        "options": [{"id": "a"}, {"id": "b"}],
        "custom_allowed": False,
    }
    comment = build_needs_human_comment(prose="reason", agent_state=state, decision=decision)

    parsed = extract_yaml_block(comment)
    assert parsed["agent_state"] == state
    assert parsed["decision"] == decision
