from flow.comment_parser import (
    AgentCommand,
    extract_agent_command,
    extract_yaml_block,
    is_authorized,
)


def test_extract_yaml_block_present():
    body = "head\n```yaml\nfoo: 1\nbar: two\n```\ntail"
    assert extract_yaml_block(body) == {"foo": 1, "bar": "two"}


def test_extract_yaml_block_missing():
    assert extract_yaml_block("plain comment, no fence") is None


def test_extract_yaml_block_malformed():
    assert extract_yaml_block("```yaml\nnot: : valid: yaml:\n```") is None


def test_simple_command():
    assert extract_agent_command("/agent start") == AgentCommand("start", None)
    assert extract_agent_command("/agent resume") == AgentCommand("resume", None)
    assert extract_agent_command("/agent abort") == AgentCommand("abort", None)


def test_decide_requires_arg():
    assert extract_agent_command("/agent decide") is None  # no arg → invalid
    assert extract_agent_command("/agent decide A") == AgentCommand("decide", "A")


def test_replan_optional_arg():
    assert extract_agent_command("/agent replan") == AgentCommand("replan", None)
    assert extract_agent_command("/agent replan use TLS") == AgentCommand("replan",
                                                                          "use TLS")


def test_unknown_command_skipped():
    assert extract_agent_command("/agent foo") is None


def test_takes_last_command():
    body = "/agent start\n/agent resume"
    assert extract_agent_command(body) == AgentCommand("resume", None)


def test_inline_prefix_allowed():
    """Humans often add a short context before the command on the same line."""
    body = "rebase main 然后继续   /agent resume"
    assert extract_agent_command(body) == AgentCommand("resume", None)


def test_inline_prefix_with_arg():
    body = "请用方案 A: /agent decide A"
    assert extract_agent_command(body) == AgentCommand("decide", "A")


def test_quoted_command_in_backticks_ignored():
    """Backtick-wrapped occurrences (typically docs/quotes) must not trigger."""
    body = "可以用 `/agent resume` 继续"
    # Preceded by a backtick, NOT whitespace → must not match.
    assert extract_agent_command(body) is None


def test_authorization():
    assert is_authorized("alice", ["alice", "bob"]) is True
    assert is_authorized("eve", ["alice", "bob"]) is False
    assert is_authorized(None, ["alice"]) is False
    assert is_authorized("alice", []) is False  # empty list = nobody
