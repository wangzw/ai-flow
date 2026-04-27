from sw.comment_parser import extract_yaml_block


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
