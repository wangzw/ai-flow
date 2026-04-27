from sw.comment_parser import extract_agent_command, extract_yaml_block


def test_extract_yaml_block_from_comment():
    comment = """## 🛑 需要决策

Some natural language description.

```yaml
agent_state:
  stage: coder
  blocker_type: ac_ambiguity
decision:
  question: "Keep history?"
  options:
    - id: keep
    - id: purge
```

后续说明。
"""
    result = extract_yaml_block(comment)
    assert result is not None
    assert result["agent_state"]["stage"] == "coder"
    assert result["decision"]["question"] == "Keep history?"
    assert len(result["decision"]["options"]) == 2


def test_extract_yaml_block_returns_none_when_missing():
    comment = "Just plain text without any block."
    assert extract_yaml_block(comment) is None


def test_extract_yaml_block_returns_none_for_malformed_yaml():
    comment = """```yaml
agent_state: {{{ broken
```"""
    assert extract_yaml_block(comment) is None


def test_extract_yaml_block_picks_first_yaml_fence_only():
    comment = """```yaml
first: 1
```

```yaml
second: 2
```"""
    result = extract_yaml_block(comment)
    assert result == {"first": 1}


def test_extract_agent_command_at_line_start():
    assert extract_agent_command("/agent resume") == "resume"
    assert extract_agent_command("Some context\n/agent retry") == "retry"


def test_extract_agent_command_unknown_command_returns_none():
    assert extract_agent_command("/agent unknown") is None


def test_extract_agent_command_not_at_line_start_ignored():
    assert extract_agent_command("please /agent resume") is None


def test_extract_agent_command_picks_last_command_when_multiple():
    # 用户多次编辑评论，最后一行命令为准
    assert extract_agent_command("/agent retry\n/agent resume") == "resume"


def test_extract_agent_command_returns_none_when_absent():
    assert extract_agent_command("just plain text") is None
