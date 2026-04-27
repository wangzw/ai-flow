# Skeleton MVP on GitLab CE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimum end-to-end loop on GitLab CE — labeling an Issue with `agent-ready` triggers a stub Coder that creates a draft MR, a stub Reviewer passes it, the MR auto-ff-merges, and the Issue ends in `agent-done`. AC validation + structured failure-path comments are real (not stubbed).

**Architecture:** Python-based framework. Core logic in `src/sw/` (state machine, comment parser, AC validator, GitLab API wrapper). Stubs for Coder/Reviewer (no LLM calls). GitLab CI as orchestration runtime; jobs use `resource_group` for state-transition atomicity. End-to-end demo on a target GitLab CE project.

**Tech Stack:** Python 3.11+, pytest, ruamel.yaml, python-gitlab, GitLab CI YAML

**Spec source:** `docs/superpowers/specs/2026-04-27-ai-coding-workflow-design.md`

**Prerequisites the user must provide before execution:**
- An accessible GitLab CE instance (URL + admin token)
- A test project (group + project name) where we'll demo
- A CI/CD Variable `GITLAB_API_TOKEN` (Project-scoped, Masked, Protected) with `api` scope
- At least one Runner registered to that project

---

## Repository Layout (after Task 1)

```
software-workflow/
├── pyproject.toml
├── README.md
├── .gitignore
├── src/sw/
│   ├── __init__.py
│   ├── comment_parser.py       # extract YAML block + /agent commands
│   ├── state_machine.py        # 5-state machine with valid transitions
│   ├── ac_validator.py         # validate Issue body has AC block
│   ├── comment_writer.py       # write double-layer needs-human comments
│   ├── gitlab_client.py        # python-gitlab wrapper, atomic label ops
│   ├── coder_stub.py           # creates trivial draft MR
│   ├── reviewer_stub.py        # always returns PASS
│   ├── label_apply.py          # apply labels.yaml to a project
│   └── handlers/
│       ├── __init__.py
│       ├── issue_handler.py    # CI entry for issue events
│       ├── comment_handler.py  # CI entry for note (comment) events
│       └── mr_handler.py       # CI entry for MR events
├── tests/sw/
│   ├── test_comment_parser.py
│   ├── test_state_machine.py
│   ├── test_ac_validator.py
│   ├── test_comment_writer.py
│   ├── test_gitlab_client.py
│   ├── test_coder_stub.py
│   ├── test_reviewer_stub.py
│   ├── test_label_apply.py
│   └── handlers/
│       ├── test_issue_handler.py
│       ├── test_comment_handler.py
│       └── test_mr_handler.py
├── config/
│   └── labels.yaml             # 5-label declarative config
├── templates/
│   ├── issue_template.md       # Issue body template (AC block placeholder)
│   └── mr_template.md          # MR description template
├── ci/
│   └── gitlab-ci.yml           # CI to be copied into target project
└── docs/superpowers/
    ├── specs/2026-04-27-ai-coding-workflow-design.md
    └── plans/2026-04-27-skeleton-mvp-gitlab-ce.md (this file)
```

---

## Task 1: Project Bootstrap

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.gitignore`
- Create: `src/sw/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Initialize git repo**

```bash
cd /Users/wangzw/workspace/software-workflow
git init
git branch -M main
```

Expected: `Initialized empty Git repository in .../.git/`

- [ ] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.venv/
.env
*.egg-info/
dist/
build/
.coverage
htmlcov/
.idea/
.vscode/
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "software-workflow"
version = "0.1.0"
description = "AI Coding workflow framework — GitLab CE skeleton MVP"
requires-python = ">=3.11"
dependencies = [
    "python-gitlab>=4.4.0",
    "ruamel.yaml>=0.18.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=5.0",
    "ruff>=0.5",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 4: Write `README.md`**

```markdown
# software-workflow

AI Coding 工作流框架 — GitLab CE 实现。

参见：
- 设计：`docs/superpowers/specs/2026-04-27-ai-coding-workflow-design.md`
- 计划：`docs/superpowers/plans/2026-04-27-skeleton-mvp-gitlab-ce.md`

## Quick start

1. 准备一个 GitLab CE 实例和测试项目
2. 在项目 CI/CD Variables 中添加 `GITLAB_API_TOKEN`（api scope, Masked, Protected）
3. 复制 `ci/gitlab-ci.yml` 到目标项目根目录改名为 `.gitlab-ci.yml`
4. 复制 `templates/` 到目标项目的 `.gitlab/issue_templates/` 和 `.gitlab/merge_request_templates/`
5. 运行 `python -m sw.label_apply --project <group/project>` 应用标签
6. 在 Issue 中按模板填写 AC，添加 `agent-ready` 标签，观察自动化流程
```

- [ ] **Step 5: Create empty package files**

```bash
mkdir -p src/sw/handlers tests/sw/handlers config templates ci
touch src/sw/__init__.py src/sw/handlers/__init__.py
touch tests/__init__.py tests/sw/__init__.py tests/sw/handlers/__init__.py
```

- [ ] **Step 6: Install deps and verify**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest --version
```

Expected: pytest version printed; no errors.

- [ ] **Step 7: Initial commit**

```bash
git add pyproject.toml README.md .gitignore src/ tests/ config/ templates/ ci/ docs/
git commit -m "chore: bootstrap project structure"
```

---

## Task 2: Comment Parser — Structured YAML Block Extractor

**Files:**
- Create: `src/sw/comment_parser.py`
- Create: `tests/sw/test_comment_parser.py`

The parser extracts YAML blocks (fenced with ` ```yaml `) from comments. This is the machine-readable channel for `agent_state` / `decision` data per spec §4.1.

- [ ] **Step 1: Write failing test for YAML block extraction**

`tests/sw/test_comment_parser.py`:
```python
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
```

- [ ] **Step 2: Run test, confirm failure**

```bash
pytest tests/sw/test_comment_parser.py -v
```

Expected: 4 errors with `ModuleNotFoundError: No module named 'sw.comment_parser'`.

- [ ] **Step 3: Implement `extract_yaml_block`**

`src/sw/comment_parser.py`:
```python
import re
from io import StringIO
from ruamel.yaml import YAML

_YAML_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def extract_yaml_block(comment: str) -> dict | None:
    """Extract the first ```yaml fenced block from a comment.

    Returns parsed dict, or None if no block exists or YAML is malformed.
    """
    match = _YAML_FENCE_RE.search(comment)
    if not match:
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(match.group(1)))
    except Exception:
        return None
```

- [ ] **Step 4: Run test, confirm pass**

```bash
pytest tests/sw/test_comment_parser.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/comment_parser.py tests/sw/test_comment_parser.py
git commit -m "feat(comment_parser): extract structured yaml block from comments"
```

---

## Task 3: Comment Parser — `/agent` Command Extractor

**Files:**
- Modify: `src/sw/comment_parser.py`
- Modify: `tests/sw/test_comment_parser.py`

Per spec §3.4, valid commands: `start`, `resume`, `retry`, `abort`, `escalate`. Commands must appear at line start to avoid matching inside prose.

- [ ] **Step 1: Add failing tests**

Append to `tests/sw/test_comment_parser.py`:
```python
from sw.comment_parser import extract_agent_command


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
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_comment_parser.py -v
```

Expected: 5 new errors `ImportError: cannot import name 'extract_agent_command'`.

- [ ] **Step 3: Implement `extract_agent_command`**

Append to `src/sw/comment_parser.py`:
```python
VALID_COMMANDS = {"start", "resume", "retry", "abort", "escalate"}

_COMMAND_RE = re.compile(r"^/agent\s+(\w+)\s*$", re.MULTILINE)


def extract_agent_command(comment: str) -> str | None:
    """Extract the last valid /agent <command> from a comment.

    Commands must appear at line start. Returns None if no valid command found.
    """
    matches = _COMMAND_RE.findall(comment)
    for cmd in reversed(matches):
        if cmd in VALID_COMMANDS:
            return cmd
    return None
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/test_comment_parser.py -v
```

Expected: 9 passed total.

- [ ] **Step 5: Commit**

```bash
git add src/sw/comment_parser.py tests/sw/test_comment_parser.py
git commit -m "feat(comment_parser): extract /agent commands from comments"
```

---

## Task 4: State Machine

**Files:**
- Create: `src/sw/state_machine.py`
- Create: `tests/sw/test_state_machine.py`

Per spec §3.1 and §3.2. 5 states + valid transitions encoded.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_state_machine.py`:
```python
import pytest

from sw.state_machine import (
    STATES,
    State,
    StateMachine,
    TransitionError,
    next_state_for_event,
)


def test_states_match_spec():
    expected = {"agent-ready", "agent-working", "needs-human", "agent-done", "agent-failed"}
    assert STATES == expected


def test_initial_label_to_ready():
    sm = StateMachine(current=None)
    sm.transition(event="label_added:agent-ready")
    assert sm.current == "agent-ready"


def test_ready_to_working_on_action_start():
    sm = StateMachine(current="agent-ready")
    sm.transition(event="action_started")
    assert sm.current == "agent-working"


def test_working_to_needs_human_on_block():
    sm = StateMachine(current="agent-working")
    sm.transition(event="agent_blocked")
    assert sm.current == "needs-human"


def test_needs_human_to_working_on_resume():
    sm = StateMachine(current="needs-human")
    sm.transition(event="command:resume")
    assert sm.current == "agent-working"


def test_working_to_done_on_merge():
    sm = StateMachine(current="agent-working")
    sm.transition(event="merged")
    assert sm.current == "agent-done"


def test_working_to_failed_on_unrecoverable():
    sm = StateMachine(current="agent-working")
    sm.transition(event="unrecoverable_error")
    assert sm.current == "agent-failed"


def test_command_abort_from_any_non_terminal():
    for state in ["agent-ready", "agent-working", "needs-human"]:
        sm = StateMachine(current=state)
        sm.transition(event="command:abort")
        assert sm.current == "agent-failed"


def test_command_escalate_from_any_non_terminal():
    for state in ["agent-ready", "agent-working"]:
        sm = StateMachine(current=state)
        sm.transition(event="command:escalate")
        assert sm.current == "needs-human"


def test_invalid_transition_raises():
    sm = StateMachine(current="agent-done")
    with pytest.raises(TransitionError):
        sm.transition(event="agent_blocked")


def test_resume_from_working_is_invalid():
    sm = StateMachine(current="agent-working")
    with pytest.raises(TransitionError):
        sm.transition(event="command:resume")


def test_next_state_for_event_pure_function():
    # Exposed for callers who don't want to instantiate StateMachine
    assert next_state_for_event("agent-working", "merged") == "agent-done"
    assert next_state_for_event("needs-human", "command:resume") == "agent-working"
    assert next_state_for_event("agent-done", "agent_blocked") is None
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_state_machine.py -v
```

Expected: ImportError for `sw.state_machine`.

- [ ] **Step 3: Implement state machine**

`src/sw/state_machine.py`:
```python
from typing import Literal

State = Literal["agent-ready", "agent-working", "needs-human", "agent-done", "agent-failed"]

STATES: set[str] = {"agent-ready", "agent-working", "needs-human", "agent-done", "agent-failed"}

_TERMINAL: set[str] = {"agent-done", "agent-failed"}

# Map (current_state_or_None, event) -> next_state
_TRANSITIONS: dict[tuple[str | None, str], str] = {
    (None, "label_added:agent-ready"): "agent-ready",
    ("agent-ready", "action_started"): "agent-working",
    ("agent-working", "agent_blocked"): "needs-human",
    ("needs-human", "command:resume"): "agent-working",
    ("agent-working", "merged"): "agent-done",
    ("agent-working", "unrecoverable_error"): "agent-failed",
    # /agent abort from any non-terminal
    ("agent-ready", "command:abort"): "agent-failed",
    ("agent-working", "command:abort"): "agent-failed",
    ("needs-human", "command:abort"): "agent-failed",
    # /agent escalate from any non-terminal
    ("agent-ready", "command:escalate"): "needs-human",
    ("agent-working", "command:escalate"): "needs-human",
    # /agent retry from any non-terminal — restart current stage (stays in same state)
    ("agent-working", "command:retry"): "agent-working",
}


class TransitionError(RuntimeError):
    pass


def next_state_for_event(current: str | None, event: str) -> str | None:
    """Pure function: compute next state, or None if event is invalid here."""
    return _TRANSITIONS.get((current, event))


class StateMachine:
    def __init__(self, current: str | None):
        self.current = current

    def transition(self, event: str) -> None:
        nxt = next_state_for_event(self.current, event)
        if nxt is None:
            raise TransitionError(
                f"Invalid event {event!r} from state {self.current!r}"
            )
        self.current = nxt

    def is_terminal(self) -> bool:
        return self.current in _TERMINAL
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tests/sw/test_state_machine.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/state_machine.py tests/sw/test_state_machine.py
git commit -m "feat(state_machine): 5-state machine with spec transitions"
```

---

## Task 5: AC Validator

**Files:**
- Create: `src/sw/ac_validator.py`
- Create: `tests/sw/test_ac_validator.py`

Per spec §2.3 and Appendix §8.1, Issue body has `<!-- ac:start --> ... <!-- ac:end -->` block. Validator checks block exists and is non-empty.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_ac_validator.py`:
```python
from sw.ac_validator import validate_ac, ValidationResult


def test_valid_ac_block():
    body = """## 原始诉求
Add /api/users pagination.

## AC
<!-- ac:start -->
Given a user lists endpoint
When called with page=2 size=10
Then response includes items 11-20
<!-- ac:end -->
"""
    result = validate_ac(body)
    assert result.valid is True


def test_missing_ac_block():
    body = "## 原始诉求\nDo something."
    result = validate_ac(body)
    assert result.valid is False
    assert "ac:start" in result.reason.lower() or "missing" in result.reason.lower()


def test_empty_ac_block():
    body = """## AC
<!-- ac:start -->

<!-- ac:end -->
"""
    result = validate_ac(body)
    assert result.valid is False
    assert "empty" in result.reason.lower()


def test_unclosed_ac_block():
    body = """## AC
<!-- ac:start -->
something
"""
    result = validate_ac(body)
    assert result.valid is False
    assert "ac:end" in result.reason.lower() or "unclosed" in result.reason.lower()


def test_ac_with_only_whitespace_is_empty():
    body = """<!-- ac:start -->
   
   
<!-- ac:end -->"""
    result = validate_ac(body)
    assert result.valid is False
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_ac_validator.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement validator**

`src/sw/ac_validator.py`:
```python
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str = ""


_AC_BLOCK_RE = re.compile(
    r"<!--\s*ac:start\s*-->(.*?)<!--\s*ac:end\s*-->",
    re.DOTALL,
)
_AC_START_RE = re.compile(r"<!--\s*ac:start\s*-->")
_AC_END_RE = re.compile(r"<!--\s*ac:end\s*-->")


def validate_ac(issue_body: str) -> ValidationResult:
    """Validate that the Issue body contains a non-empty AC block."""
    has_start = bool(_AC_START_RE.search(issue_body))
    has_end = bool(_AC_END_RE.search(issue_body))

    if not has_start:
        return ValidationResult(valid=False, reason="Missing <!-- ac:start --> marker")
    if not has_end:
        return ValidationResult(valid=False, reason="Unclosed AC block: <!-- ac:end --> not found")

    match = _AC_BLOCK_RE.search(issue_body)
    if match is None:
        return ValidationResult(valid=False, reason="AC block markers found but not paired correctly")

    content = match.group(1).strip()
    if not content:
        return ValidationResult(valid=False, reason="AC block is empty")

    return ValidationResult(valid=True)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/test_ac_validator.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/ac_validator.py tests/sw/test_ac_validator.py
git commit -m "feat(ac_validator): validate AC block presence and non-emptiness"
```

---

## Task 6: Comment Writer (Double-Layer Format)

**Files:**
- Create: `src/sw/comment_writer.py`
- Create: `tests/sw/test_comment_writer.py`

Per spec §4.1, the structured comment has natural-language section + ` ```yaml ` block with `agent_state`, `decision`, `resume_instruction`. Used when transitioning to `needs-human`.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_comment_writer.py`:
```python
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
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_comment_writer.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement comment writer**

`src/sw/comment_writer.py`:
```python
from io import StringIO
from ruamel.yaml import YAML

_TEMPLATE = """## 🛑 需要人类决策

{prose}

```yaml
{yaml_block}```

请在评论中明确选择，然后输入 `/agent resume`。
"""


def build_needs_human_comment(
    *, prose: str, agent_state: dict, decision: dict
) -> str:
    """Build a double-layer needs-human comment per spec §4.1."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)

    payload = {
        "agent_state": agent_state,
        "decision": decision,
        "resume_instruction": "回复评论选择决策，然后输入 /agent resume",
    }
    buf = StringIO()
    yaml.dump(payload, buf)

    return _TEMPLATE.format(prose=prose, yaml_block=buf.getvalue())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/test_comment_writer.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/comment_writer.py tests/sw/test_comment_writer.py
git commit -m "feat(comment_writer): build double-layer needs-human comments"
```

---

## Task 7: Labels Config

**Files:**
- Create: `config/labels.yaml`

Declarative config defining the 5 labels. Used by `label_apply.py` (Task 8) to ensure target projects have them.

- [ ] **Step 1: Write `config/labels.yaml`**

```yaml
labels:
  - name: agent-ready
    color: "#1F75CB"
    description: "AC 就绪，待派发给 Agent"

  - name: agent-working
    color: "#FFA500"
    description: "Agent 正在工作，人勿扰"

  - name: needs-human
    color: "#D9534F"
    description: "Agent 卡住，等人类回应"

  - name: agent-done
    color: "#1A7F37"
    description: "Agent 已完成（终态：成功）"

  - name: agent-failed
    color: "#5D5D5D"
    description: "Agent 失败（终态：不可恢复）"
```

- [ ] **Step 2: Commit**

```bash
git add config/labels.yaml
git commit -m "feat(config): declarative labels config"
```

---

## Task 8: GitLab Client (Atomic Label Operations)

**Files:**
- Create: `src/sw/gitlab_client.py`
- Create: `tests/sw/test_gitlab_client.py`

Wraps `python-gitlab` to provide:
- `set_state_label(issue, new_label)`: atomic moveset — removes all `agent-*` labels, adds `new_label`
- `comment_on_issue(issue, body)`
- `get_issue(project, iid)`

The `set_state_label` operation is the spec §3.5 "label 切换原子化" requirement. GitLab's labels API doesn't have transaction semantics, so we approximate atomicity by computing the final label list and doing one PUT (replace all labels).

- [ ] **Step 1: Write failing tests with mocked python-gitlab**

`tests/sw/test_gitlab_client.py`:
```python
from unittest.mock import MagicMock

import pytest

from sw.gitlab_client import GitLabClient, AGENT_LABEL_PREFIX


@pytest.fixture
def fake_issue():
    issue = MagicMock()
    issue.labels = ["agent-ready", "bug", "priority/high"]
    return issue


def test_set_state_label_removes_all_agent_prefixed_then_adds_new(fake_issue):
    client = GitLabClient(gl=MagicMock())
    client.set_state_label(fake_issue, new_label="agent-working")

    # The new labels should preserve non-agent-* labels and contain only the new agent-*
    new_labels = sorted(fake_issue.labels)
    assert "agent-ready" not in new_labels
    assert "agent-working" in new_labels
    assert "bug" in new_labels
    assert "priority/high" in new_labels
    fake_issue.save.assert_called_once()


def test_set_state_label_with_no_existing_agent_label(fake_issue):
    fake_issue.labels = ["bug"]
    client = GitLabClient(gl=MagicMock())
    client.set_state_label(fake_issue, new_label="agent-ready")
    assert "agent-ready" in fake_issue.labels
    assert "bug" in fake_issue.labels


def test_set_state_label_rejects_non_agent_prefix(fake_issue):
    client = GitLabClient(gl=MagicMock())
    with pytest.raises(ValueError, match="must start with"):
        client.set_state_label(fake_issue, new_label="some-other-label")


def test_comment_on_issue_calls_notes_create():
    issue = MagicMock()
    client = GitLabClient(gl=MagicMock())
    client.comment_on_issue(issue, "hello")
    issue.notes.create.assert_called_once_with({"body": "hello"})


def test_agent_label_prefix_constant():
    assert AGENT_LABEL_PREFIX == "agent-"
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_gitlab_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement client**

`src/sw/gitlab_client.py`:
```python
from typing import Iterable

import gitlab

AGENT_LABEL_PREFIX = "agent-"
NEEDS_HUMAN_LABEL = "needs-human"
_VALID_STATE_LABELS = {
    "agent-ready",
    "agent-working",
    "agent-done",
    "agent-failed",
    NEEDS_HUMAN_LABEL,
}


def _is_state_label(label: str) -> bool:
    return label.startswith(AGENT_LABEL_PREFIX) or label == NEEDS_HUMAN_LABEL


class GitLabClient:
    def __init__(self, gl: gitlab.Gitlab):
        self._gl = gl

    @classmethod
    def from_env(cls, url: str, token: str) -> "GitLabClient":
        gl = gitlab.Gitlab(url=url, private_token=token)
        return cls(gl=gl)

    def set_state_label(self, issue, new_label: str) -> None:
        """Atomically replace any state labels with new_label.

        State labels = labels in {agent-ready, agent-working, agent-done, agent-failed, needs-human}.
        Other labels (e.g. bug, priority/high) are preserved.
        """
        if new_label not in _VALID_STATE_LABELS:
            raise ValueError(
                f"new_label {new_label!r} must start with {AGENT_LABEL_PREFIX} "
                f"or be {NEEDS_HUMAN_LABEL!r}; valid: {sorted(_VALID_STATE_LABELS)}"
            )
        non_state = [lbl for lbl in issue.labels if not _is_state_label(lbl)]
        issue.labels = [*non_state, new_label]
        issue.save()

    def comment_on_issue(self, issue, body: str) -> None:
        issue.notes.create({"body": body})

    def get_project(self, project_path: str):
        return self._gl.projects.get(project_path)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/test_gitlab_client.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/gitlab_client.py tests/sw/test_gitlab_client.py
git commit -m "feat(gitlab_client): atomic state-label operations"
```

---

## Task 9: Label Apply Script

**Files:**
- Create: `src/sw/label_apply.py`
- Create: `tests/sw/test_label_apply.py`

Script to apply `config/labels.yaml` to a target GitLab project. Idempotent: creates missing labels, updates colors/descriptions if changed.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_label_apply.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock

from sw.label_apply import apply_labels, load_labels_config


def test_load_labels_config(tmp_path: Path):
    cfg = tmp_path / "labels.yaml"
    cfg.write_text(
        """labels:
  - name: agent-ready
    color: "#1F75CB"
    description: "AC ready"
"""
    )
    labels = load_labels_config(cfg)
    assert labels == [{"name": "agent-ready", "color": "#1F75CB", "description": "AC ready"}]


def test_apply_labels_creates_missing():
    project = MagicMock()
    project.labels.list.return_value = []  # no existing
    desired = [{"name": "agent-ready", "color": "#1F75CB", "description": "x"}]

    apply_labels(project, desired)

    project.labels.create.assert_called_once_with(
        {"name": "agent-ready", "color": "#1F75CB", "description": "x"}
    )


def test_apply_labels_updates_existing_on_color_drift():
    existing = MagicMock()
    existing.name = "agent-ready"
    existing.color = "#000000"
    existing.description = "old"
    project = MagicMock()
    project.labels.list.return_value = [existing]

    desired = [{"name": "agent-ready", "color": "#1F75CB", "description": "new"}]
    apply_labels(project, desired)

    assert existing.color == "#1F75CB"
    assert existing.description == "new"
    existing.save.assert_called_once()
    project.labels.create.assert_not_called()


def test_apply_labels_no_op_when_synced():
    existing = MagicMock()
    existing.name = "agent-ready"
    existing.color = "#1F75CB"
    existing.description = "AC ready"
    project = MagicMock()
    project.labels.list.return_value = [existing]

    desired = [{"name": "agent-ready", "color": "#1F75CB", "description": "AC ready"}]
    apply_labels(project, desired)

    existing.save.assert_not_called()
    project.labels.create.assert_not_called()
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_label_apply.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement label apply**

`src/sw/label_apply.py`:
```python
import argparse
import os
import sys
from pathlib import Path
from io import StringIO

from ruamel.yaml import YAML

from sw.gitlab_client import GitLabClient


def load_labels_config(path: Path) -> list[dict]:
    yaml = YAML(typ="safe")
    data = yaml.load(StringIO(path.read_text()))
    return data["labels"]


def apply_labels(project, desired: list[dict]) -> None:
    """Sync labels to a GitLab project: create missing, update drifted."""
    existing = {label.name: label for label in project.labels.list(get_all=True)}

    for spec in desired:
        name = spec["name"]
        if name not in existing:
            project.labels.create(spec)
            continue
        lbl = existing[name]
        drift = lbl.color != spec["color"] or lbl.description != spec["description"]
        if drift:
            lbl.color = spec["color"]
            lbl.description = spec["description"]
            lbl.save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="GitLab project path, e.g. 'group/repo'")
    parser.add_argument("--config", default="config/labels.yaml")
    parser.add_argument("--gitlab-url", default=os.environ.get("CI_SERVER_URL", "https://gitlab.com"))
    parser.add_argument("--token", default=os.environ.get("GITLAB_API_TOKEN"))
    args = parser.parse_args(argv)

    if not args.token:
        parser.error("GITLAB_API_TOKEN env var or --token required")

    desired = load_labels_config(Path(args.config))
    client = GitLabClient.from_env(url=args.gitlab_url, token=args.token)
    project = client.get_project(args.project)
    apply_labels(project, desired)
    print(f"Applied {len(desired)} labels to {args.project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/test_label_apply.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/label_apply.py tests/sw/test_label_apply.py
git commit -m "feat(label_apply): idempotent label sync from config"
```

---

## Task 10: Issue and MR Templates

**Files:**
- Create: `templates/issue_template.md`
- Create: `templates/mr_template.md`

- [ ] **Step 1: Write Issue template**

`templates/issue_template.md`:
```markdown
## 任务类型

- [ ] A — 机械型 bug 修复
- [ ] B — 接口已定的功能增强
- [ ] C — 跨模块清晰需求

## 原始诉求

<!-- 描述你想解决的问题或想增加的能力（自然语言） -->

## AC（验收标准）

<!-- 由上游 AC 子系统填入；手动创建时也可在此手写严谨 AC -->

<!-- ac:start -->

<!-- ac:end -->

## 关联文档

<!-- PRD / 设计文档 / 相关 Issue 链接 -->
```

- [ ] **Step 2: Write MR template**

`templates/mr_template.md`:
```markdown
<!-- This MR was created by an Agent. -->

## 关联 Issue

<!-- Closes #ISSUE_NUMBER -->

## 变更摘要

<!-- 由 Coder Agent 自动填写 -->

## AC 满足情况

<!-- 由 Coder Agent 自动填写：每条 AC 对应的实现 + 测试 -->

## Reviewer 矩阵结果

<!-- 由 CI 自动填写 -->
```

- [ ] **Step 3: Commit**

```bash
git add templates/
git commit -m "feat(templates): issue and mr templates with AC block"
```

---

## Task 11: Stub Reviewer Agent

**Files:**
- Create: `src/sw/reviewer_stub.py`
- Create: `tests/sw/test_reviewer_stub.py`

For MVP: a stub that always returns PASS. Establishes the Reviewer interface.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_reviewer_stub.py`:
```python
from sw.reviewer_stub import ReviewResult, run_review_matrix


def test_stub_returns_all_pass():
    result = run_review_matrix(mr_iid=42, project_path="g/r")
    assert isinstance(result, ReviewResult)
    assert result.all_passed is True
    assert result.failed_dimensions == []


def test_stub_includes_all_must_dimensions():
    result = run_review_matrix(mr_iid=42, project_path="g/r")
    expected = {
        "ac_compliance",
        "test_quality",
        "security",
        "performance",
        "consistency",
        "documentation_sync",
        "migration_safety",
    }
    assert set(result.dimension_results.keys()) == expected
    for status in result.dimension_results.values():
        assert status == "PASS"
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_reviewer_stub.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement stub**

`src/sw/reviewer_stub.py`:
```python
from dataclasses import dataclass, field

MUST_DIMENSIONS = (
    "ac_compliance",
    "test_quality",
    "security",
    "performance",
    "consistency",
    "documentation_sync",
    "migration_safety",
)


@dataclass(frozen=True)
class ReviewResult:
    all_passed: bool
    dimension_results: dict[str, str]  # dimension -> "PASS" | "FAIL"
    failed_dimensions: list[str] = field(default_factory=list)


def run_review_matrix(*, mr_iid: int, project_path: str) -> ReviewResult:
    """Stub: always returns PASS for all MUST dimensions.

    Real implementation will dispatch to per-dimension Reviewer Agents.
    """
    dim_results = {dim: "PASS" for dim in MUST_DIMENSIONS}
    return ReviewResult(all_passed=True, dimension_results=dim_results, failed_dimensions=[])
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/test_reviewer_stub.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/reviewer_stub.py tests/sw/test_reviewer_stub.py
git commit -m "feat(reviewer_stub): always-PASS stub establishing reviewer interface"
```

---

## Task 12: Stub Coder Agent

**Files:**
- Create: `src/sw/coder_stub.py`
- Create: `tests/sw/test_coder_stub.py`

For MVP: creates a branch, adds a trivial file (`AGENT_LOG.md` with timestamp), pushes, opens a draft MR. No LLM, no real coding.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_coder_stub.py`:
```python
from unittest.mock import MagicMock, patch

from sw.coder_stub import run_coder, CoderResult


def test_run_coder_creates_branch_and_mr():
    project = MagicMock()
    project.default_branch = "main"
    project.path_with_namespace = "g/r"

    branch = MagicMock()
    branch.name = "agent/issue-42"
    project.branches.create.return_value = branch

    project.commits.create.return_value = MagicMock()

    mr = MagicMock()
    mr.iid = 100
    project.mergerequests.create.return_value = mr

    result = run_coder(project=project, issue_iid=42, issue_title="test")

    assert isinstance(result, CoderResult)
    assert result.success is True
    assert result.mr_iid == 100
    project.branches.create.assert_called_once()
    project.commits.create.assert_called_once()
    project.mergerequests.create.assert_called_once()


def test_branch_name_includes_issue_iid():
    project = MagicMock()
    project.default_branch = "main"
    branch = MagicMock()
    branch.name = "agent/issue-42"
    project.branches.create.return_value = branch
    project.mergerequests.create.return_value = MagicMock(iid=1)

    run_coder(project=project, issue_iid=42, issue_title="t")

    call_args = project.branches.create.call_args[0][0]
    assert "42" in call_args["branch"]
    assert call_args["ref"] == "main"


def test_mr_is_draft():
    project = MagicMock()
    project.default_branch = "main"
    project.branches.create.return_value = MagicMock(name="agent/issue-1")
    project.mergerequests.create.return_value = MagicMock(iid=1)

    run_coder(project=project, issue_iid=1, issue_title="t")

    mr_args = project.mergerequests.create.call_args[0][0]
    title = mr_args["title"]
    assert title.startswith("Draft:") or mr_args.get("draft") is True
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/test_coder_stub.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement coder stub**

`src/sw/coder_stub.py`:
```python
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CoderResult:
    success: bool
    mr_iid: int | None
    branch_name: str
    error: str = ""


def run_coder(*, project, issue_iid: int, issue_title: str) -> CoderResult:
    """Stub Coder: creates a branch, adds AGENT_LOG.md, opens draft MR.

    Real implementation will:
    - validate AC
    - call Claude Code with PRD/AC context
    - iterate until tests pass locally
    - write WHY into code comments (per spec §5.3)
    """
    branch_name = f"agent/issue-{issue_iid}"
    base = project.default_branch

    project.branches.create({"branch": branch_name, "ref": base})

    timestamp = datetime.now(timezone.utc).isoformat()
    project.commits.create(
        {
            "branch": branch_name,
            "commit_message": f"chore(stub): touched by Coder Agent for issue #{issue_iid}",
            "actions": [
                {
                    "action": "create",
                    "file_path": "AGENT_LOG.md",
                    "content": f"# Agent Log\n\n- {timestamp}: stub coder ran for issue #{issue_iid}\n",
                }
            ],
        }
    )

    mr = project.mergerequests.create(
        {
            "source_branch": branch_name,
            "target_branch": base,
            "title": f"Draft: stub for issue #{issue_iid} — {issue_title}",
            "description": f"Stub MR auto-generated for issue #{issue_iid}.\n\nCloses #{issue_iid}",
            "remove_source_branch": True,
        }
    )

    return CoderResult(success=True, mr_iid=mr.iid, branch_name=branch_name)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/test_coder_stub.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/coder_stub.py tests/sw/test_coder_stub.py
git commit -m "feat(coder_stub): trivial draft MR creation establishing coder interface"
```

---

## Task 13: Issue Handler (CI Entry Point for Issue Events)

**Files:**
- Create: `src/sw/handlers/issue_handler.py`
- Create: `tests/sw/handlers/test_issue_handler.py`

Triggered by GitLab CI `issue` events. Reads webhook-style payload from env. If `agent-ready` was added, run AC validation; if pass, transition to `agent-working` and run Coder.

GitLab CI exposes the triggering event in env (`CI_PIPELINE_SOURCE`, plus the project/issue context). For MVP, we read explicit env vars set by the pipeline definition.

- [ ] **Step 1: Write failing tests**

`tests/sw/handlers/test_issue_handler.py`:
```python
from unittest.mock import MagicMock, patch

from sw.handlers.issue_handler import handle_issue_event


def _make_issue(*, body: str, labels: list[str], iid: int = 42, title: str = "t"):
    issue = MagicMock()
    issue.description = body
    issue.labels = list(labels)
    issue.iid = iid
    issue.title = title
    return issue


VALID_BODY = """## AC
<!-- ac:start -->
something testable
<!-- ac:end -->
"""


def test_label_added_agent_ready_with_valid_ac_runs_coder():
    project = MagicMock()
    issue = _make_issue(body=VALID_BODY, labels=["agent-ready"])
    project.issues.get.return_value = issue

    coder = MagicMock(return_value=MagicMock(success=True, mr_iid=99))
    client = MagicMock()

    handle_issue_event(
        project=project,
        issue_iid=42,
        action="label_added",
        label="agent-ready",
        client=client,
        coder=coder,
    )

    # transitioned ready -> working before invoking coder
    set_calls = client.set_state_label.call_args_list
    labels_set = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-working" in labels_set
    coder.assert_called_once()


def test_label_added_agent_ready_with_missing_ac_transitions_to_needs_human():
    project = MagicMock()
    issue = _make_issue(body="no AC here", labels=["agent-ready"])
    project.issues.get.return_value = issue

    coder = MagicMock()
    client = MagicMock()

    handle_issue_event(
        project=project,
        issue_iid=42,
        action="label_added",
        label="agent-ready",
        client=client,
        coder=coder,
    )

    set_calls = client.set_state_label.call_args_list
    labels_set = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "needs-human" in labels_set
    coder.assert_not_called()
    client.comment_on_issue.assert_called_once()
    body = client.comment_on_issue.call_args[0][1]
    assert "ac" in body.lower()


def test_other_label_does_nothing():
    project = MagicMock()
    issue = _make_issue(body=VALID_BODY, labels=["bug"])
    project.issues.get.return_value = issue

    coder = MagicMock()
    client = MagicMock()

    handle_issue_event(
        project=project,
        issue_iid=42,
        action="label_added",
        label="bug",
        client=client,
        coder=coder,
    )

    client.set_state_label.assert_not_called()
    coder.assert_not_called()
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/handlers/test_issue_handler.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement issue handler**

`src/sw/handlers/issue_handler.py`:
```python
from typing import Callable

from sw.ac_validator import validate_ac
from sw.comment_writer import build_needs_human_comment
from sw.coder_stub import run_coder


def handle_issue_event(
    *,
    project,
    issue_iid: int,
    action: str,
    label: str | None,
    client,
    coder: Callable | None = None,
) -> None:
    """Dispatch handler for issue events from GitLab CI.

    Currently handles only `action='label_added' && label='agent-ready'`.
    """
    if action != "label_added" or label != "agent-ready":
        return

    coder = coder or (lambda **kw: run_coder(**kw))

    issue = project.issues.get(issue_iid)
    result = validate_ac(issue.description or "")

    if not result.valid:
        comment = build_needs_human_comment(
            prose=f"AC 验收失败：{result.reason}。请补充 AC 后重新打 `agent-ready` 标签。",
            agent_state={"stage": "ac_validation", "blocker_type": "ac_invalid"},
            decision={
                "question": "如何修复 AC？",
                "options": [
                    {"id": "edit_issue", "desc": "编辑 Issue body 补充 AC，移除并重打 agent-ready"},
                ],
                "custom_allowed": True,
            },
        )
        client.comment_on_issue(issue, comment)
        client.set_state_label(issue, "needs-human")
        return

    client.set_state_label(issue, "agent-working")
    coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/handlers/test_issue_handler.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/handlers/issue_handler.py tests/sw/handlers/test_issue_handler.py
git commit -m "feat(handlers): issue_handler runs AC validation and dispatches coder"
```

---

## Task 14: Comment Handler (CI Entry Point for Note Events)

**Files:**
- Create: `src/sw/handlers/comment_handler.py`
- Create: `tests/sw/handlers/test_comment_handler.py`

Parses comment for `/agent <command>`, applies the corresponding state transition. For MVP, fully supports `resume`, `abort`, `escalate`. `start` and `retry` are handled minimally.

- [ ] **Step 1: Write failing tests**

`tests/sw/handlers/test_comment_handler.py`:
```python
from unittest.mock import MagicMock

import pytest

from sw.handlers.comment_handler import handle_comment_event


def _make_issue(labels):
    issue = MagicMock()
    issue.labels = list(labels)
    issue.iid = 42
    return issue


def test_resume_from_needs_human_transitions_to_working():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["needs-human"])
    client = MagicMock()
    coder = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="ok do option keep\n/agent resume",
        client=client,
        coder=coder,
    )

    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-working" in labels
    coder.assert_called_once()


def test_abort_transitions_to_failed():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="/agent abort",
        client=client,
        coder=MagicMock(),
    )

    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-failed" in labels


def test_escalate_transitions_to_needs_human():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="/agent escalate",
        client=client,
        coder=MagicMock(),
    )

    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "needs-human" in labels


def test_resume_from_invalid_state_is_no_op():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()
    coder = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="/agent resume",
        client=client,
        coder=coder,
    )

    client.set_state_label.assert_not_called()
    coder.assert_not_called()


def test_no_command_is_no_op():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="just chatting",
        client=client,
        coder=MagicMock(),
    )

    client.set_state_label.assert_not_called()
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/handlers/test_comment_handler.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement comment handler**

`src/sw/handlers/comment_handler.py`:
```python
from typing import Callable

from sw.comment_parser import extract_agent_command
from sw.coder_stub import run_coder
from sw.state_machine import next_state_for_event


def _current_state_label(labels: list[str]) -> str | None:
    state_labels = {"agent-ready", "agent-working", "agent-done", "agent-failed", "needs-human"}
    for lbl in labels:
        if lbl in state_labels:
            return lbl
    return None


def handle_comment_event(
    *,
    project,
    issue_iid: int,
    comment_body: str,
    client,
    coder: Callable | None = None,
) -> None:
    cmd = extract_agent_command(comment_body)
    if cmd is None:
        return

    issue = project.issues.get(issue_iid)
    current = _current_state_label(issue.labels)
    next_label = next_state_for_event(current, f"command:{cmd}")
    if next_label is None:
        # Invalid command for current state — silently no-op.
        # (Real implementation may post a clarifying comment.)
        return

    client.set_state_label(issue, next_label)

    # Side-effect: resume re-dispatches the coder.
    if cmd == "resume":
        coder = coder or (lambda **kw: run_coder(**kw))
        coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/handlers/test_comment_handler.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/handlers/comment_handler.py tests/sw/handlers/test_comment_handler.py
git commit -m "feat(handlers): comment_handler dispatches /agent commands"
```

---

## Task 15: MR Handler (CI Entry Point for MR Events)

**Files:**
- Create: `src/sw/handlers/mr_handler.py`
- Create: `tests/sw/handlers/test_mr_handler.py`

When an Agent's draft MR is "ready" (no longer Draft), run the Reviewer matrix. On all-pass: rebase → ff-merge → transition the linked Issue to `agent-done`. (No merge queue in MVP — direct ff.)

For MVP, we **trigger** the MR pipeline manually after Coder finishes. Future: real GitLab webhook.

- [ ] **Step 1: Write failing tests**

`tests/sw/handlers/test_mr_handler.py`:
```python
from unittest.mock import MagicMock, patch

from sw.handlers.mr_handler import handle_mr_ready


def test_all_pass_merges_and_marks_issue_done():
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.description = "Closes #42"
    project.mergerequests.get.return_value = mr

    issue = MagicMock()
    issue.labels = ["agent-working"]
    issue.iid = 42
    project.issues.get.return_value = issue

    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))
    client = MagicMock()

    handle_mr_ready(
        project=project,
        mr_iid=100,
        client=client,
        reviewer=reviewer,
    )

    mr.merge.assert_called_once()
    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-done" in labels


def test_any_fail_does_not_merge_and_keeps_working():
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.description = "Closes #42"
    project.mergerequests.get.return_value = mr

    issue = MagicMock()
    issue.labels = ["agent-working"]
    issue.iid = 42
    project.issues.get.return_value = issue

    reviewer = MagicMock(return_value=MagicMock(all_passed=False, failed_dimensions=["security"]))
    client = MagicMock()

    handle_mr_ready(
        project=project,
        mr_iid=100,
        client=client,
        reviewer=reviewer,
    )

    mr.merge.assert_not_called()
    client.set_state_label.assert_not_called()


def test_extracts_issue_iid_from_description_closes_pattern():
    from sw.handlers.mr_handler import _extract_closing_issue_iid

    assert _extract_closing_issue_iid("Closes #42") == 42
    assert _extract_closing_issue_iid("- closes #99\nstuff") == 99
    assert _extract_closing_issue_iid("see issue 42") is None
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest tests/sw/handlers/test_mr_handler.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement MR handler**

`src/sw/handlers/mr_handler.py`:
```python
import re
from typing import Callable

from sw.reviewer_stub import run_review_matrix


_CLOSES_RE = re.compile(r"closes\s+#(\d+)", re.IGNORECASE)


def _extract_closing_issue_iid(mr_description: str) -> int | None:
    m = _CLOSES_RE.search(mr_description or "")
    return int(m.group(1)) if m else None


def handle_mr_ready(
    *,
    project,
    mr_iid: int,
    client,
    reviewer: Callable | None = None,
) -> None:
    """Run the Reviewer matrix on a ready MR. On all-pass: ff-merge + Issue done."""
    reviewer = reviewer or (lambda **kw: run_review_matrix(**kw))

    mr = project.mergerequests.get(mr_iid)
    result = reviewer(mr_iid=mr_iid, project_path=project.path_with_namespace)

    if not result.all_passed:
        # MVP: leave for future "agent-fixing"-style loop. For now, do nothing.
        return

    # ff-merge — rebase before merge to keep linear history (per spec §5.5)
    mr.rebase()
    mr.merge(merge_when_pipeline_succeeds=False, should_remove_source_branch=True)

    issue_iid = _extract_closing_issue_iid(mr.description)
    if issue_iid is None:
        return
    issue = project.issues.get(issue_iid)
    client.set_state_label(issue, "agent-done")
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/sw/handlers/test_mr_handler.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sw/handlers/mr_handler.py tests/sw/handlers/test_mr_handler.py
git commit -m "feat(handlers): mr_handler runs reviewer matrix and ff-merges"
```

---

## Task 16: GitLab CI Configuration

**Files:**
- Create: `ci/gitlab-ci.yml`

The CI definition that target projects copy as `.gitlab-ci.yml`. Three job groups corresponding to the three handlers. Uses `resource_group` to serialize state-label mutations on the same Issue.

- [ ] **Step 1: Write `ci/gitlab-ci.yml`**

```yaml
stages:
  - dispatch

# Common defaults
default:
  image: python:3.11-slim
  before_script:
    - pip install --quiet python-gitlab ruamel.yaml
    - pip install --quiet -e "git+${SW_FRAMEWORK_GIT_URL}@${SW_FRAMEWORK_REF:-main}#egg=software-workflow"

# Issue events: triggered by issue Webhook (or a manual scheduler)
# We expect the dispatcher to set CI_TRIGGERED_EVENT and SW_ISSUE_IID/SW_LABEL_ADDED.
issue_event:
  stage: dispatch
  rules:
    - if: '$CI_TRIGGERED_EVENT == "issue_label_added"'
  resource_group: "agent-issue-${SW_ISSUE_IID}"
  script:
    - |
      python - <<'PY'
      import os
      from sw.gitlab_client import GitLabClient
      from sw.handlers.issue_handler import handle_issue_event
      gl = GitLabClient.from_env(url=os.environ["CI_SERVER_URL"], token=os.environ["GITLAB_API_TOKEN"])
      project = gl.get_project(os.environ["CI_PROJECT_PATH"])
      handle_issue_event(
          project=project,
          issue_iid=int(os.environ["SW_ISSUE_IID"]),
          action="label_added",
          label=os.environ["SW_LABEL_ADDED"],
          client=gl,
      )
      PY

comment_event:
  stage: dispatch
  rules:
    - if: '$CI_TRIGGERED_EVENT == "issue_note_added"'
  resource_group: "agent-issue-${SW_ISSUE_IID}"
  script:
    - |
      python - <<'PY'
      import os
      from sw.gitlab_client import GitLabClient
      from sw.handlers.comment_handler import handle_comment_event
      gl = GitLabClient.from_env(url=os.environ["CI_SERVER_URL"], token=os.environ["GITLAB_API_TOKEN"])
      project = gl.get_project(os.environ["CI_PROJECT_PATH"])
      handle_comment_event(
          project=project,
          issue_iid=int(os.environ["SW_ISSUE_IID"]),
          comment_body=os.environ["SW_COMMENT_BODY"],
          client=gl,
      )
      PY

mr_ready_event:
  stage: dispatch
  rules:
    - if: '$CI_TRIGGERED_EVENT == "mr_ready"'
  resource_group: "agent-mr-${SW_MR_IID}"
  script:
    - |
      python - <<'PY'
      import os
      from sw.gitlab_client import GitLabClient
      from sw.handlers.mr_handler import handle_mr_ready
      gl = GitLabClient.from_env(url=os.environ["CI_SERVER_URL"], token=os.environ["GITLAB_API_TOKEN"])
      project = gl.get_project(os.environ["CI_PROJECT_PATH"])
      handle_mr_ready(
          project=project,
          mr_iid=int(os.environ["SW_MR_IID"]),
          client=gl,
      )
      PY
```

> **Note**: GitLab CE webhooks → CI Pipeline triggers require either (a) a small relay service that translates webhook payloads into pipeline trigger calls with the `CI_TRIGGERED_EVENT` / `SW_*` env vars, or (b) GitLab Premium's "Pipelines for Webhooks" feature. For MVP, we use (a). The relay is implemented in Task 17.

- [ ] **Step 2: Commit**

```bash
git add ci/gitlab-ci.yml
git commit -m "feat(ci): gitlab-ci.yml dispatching three handler types"
```

---

## Task 17: Webhook Relay Service

**Files:**
- Create: `src/sw/webhook_relay.py`
- Create: `tests/sw/test_webhook_relay.py`

A minimal Flask service that receives GitLab webhooks and triggers the corresponding CI pipeline with `CI_TRIGGERED_EVENT` and `SW_*` env vars. Self-hosted as a sidecar service.

- [ ] **Step 1: Add Flask to deps**

Edit `pyproject.toml`:
```toml
dependencies = [
    "python-gitlab>=4.4.0",
    "ruamel.yaml>=0.18.0",
    "flask>=3.0",
]
```

```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Write failing tests**

`tests/sw/test_webhook_relay.py`:
```python
from unittest.mock import MagicMock, patch

import pytest

from sw.webhook_relay import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GITLAB_API_TOKEN", "fake-token")
    monkeypatch.setenv("WEBHOOK_SECRET", "shared-secret")
    app = create_app()
    return app.test_client()


def _post(client, payload, headers=None):
    h = {"X-Gitlab-Token": "shared-secret", **(headers or {})}
    return client.post("/webhook", json=payload, headers=h)


def test_rejects_missing_token(client):
    resp = client.post("/webhook", json={})
    assert resp.status_code == 401


def test_rejects_wrong_token(client):
    resp = client.post("/webhook", json={}, headers={"X-Gitlab-Token": "wrong"})
    assert resp.status_code == 401


def test_label_added_triggers_pipeline(client, monkeypatch):
    triggered = {}

    def fake_trigger(project_path, ref, variables):
        triggered.update(project_path=project_path, ref=ref, variables=variables)

    monkeypatch.setattr("sw.webhook_relay._trigger_pipeline", fake_trigger)

    payload = {
        "object_kind": "issue",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "object_attributes": {"iid": 42, "action": "update"},
        "changes": {"labels": {"previous": [], "current": [{"title": "agent-ready"}]}},
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert triggered["variables"]["CI_TRIGGERED_EVENT"] == "issue_label_added"
    assert triggered["variables"]["SW_ISSUE_IID"] == "42"
    assert triggered["variables"]["SW_LABEL_ADDED"] == "agent-ready"


def test_note_added_on_issue_triggers_pipeline(client, monkeypatch):
    triggered = {}
    monkeypatch.setattr(
        "sw.webhook_relay._trigger_pipeline",
        lambda **kw: triggered.update(**kw),
    )

    payload = {
        "object_kind": "note",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "issue": {"iid": 42},
        "object_attributes": {"note": "/agent resume", "noteable_type": "Issue"},
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert triggered["variables"]["CI_TRIGGERED_EVENT"] == "issue_note_added"
    assert triggered["variables"]["SW_COMMENT_BODY"] == "/agent resume"


def test_mr_ready_triggers_pipeline(client, monkeypatch):
    triggered = {}
    monkeypatch.setattr(
        "sw.webhook_relay._trigger_pipeline",
        lambda **kw: triggered.update(**kw),
    )
    payload = {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "object_attributes": {
            "iid": 100,
            "action": "update",
            "oldrev": None,
            "work_in_progress": False,
        },
        "changes": {"draft": {"previous": True, "current": False}},
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert triggered["variables"]["CI_TRIGGERED_EVENT"] == "mr_ready"
    assert triggered["variables"]["SW_MR_IID"] == "100"


def test_unrelated_event_is_no_op(client, monkeypatch):
    called = []
    monkeypatch.setattr("sw.webhook_relay._trigger_pipeline", lambda **kw: called.append(kw))

    payload = {"object_kind": "push", "project": {"path_with_namespace": "g/r"}}
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert called == []
```

- [ ] **Step 3: Run, confirm failure**

```bash
pytest tests/sw/test_webhook_relay.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement relay**

`src/sw/webhook_relay.py`:
```python
import os

import gitlab
from flask import Flask, jsonify, request


def create_app() -> Flask:
    app = Flask(__name__)
    secret = os.environ["WEBHOOK_SECRET"]

    @app.post("/webhook")
    def webhook():
        if request.headers.get("X-Gitlab-Token") != secret:
            return jsonify({"error": "unauthorized"}), 401

        payload = request.get_json(silent=True) or {}
        kind = payload.get("object_kind")
        project_path = (payload.get("project") or {}).get("path_with_namespace")
        if not project_path:
            return jsonify({"ok": True, "ignored": "no project path"}), 200

        triggered = False

        if kind == "issue":
            triggered = _maybe_trigger_issue(payload, project_path)
        elif kind == "note":
            triggered = _maybe_trigger_note(payload, project_path)
        elif kind == "merge_request":
            triggered = _maybe_trigger_mr(payload, project_path)

        return jsonify({"ok": True, "triggered": triggered}), 200

    return app


def _maybe_trigger_issue(payload: dict, project_path: str) -> bool:
    changes = payload.get("changes", {})
    label_change = changes.get("labels")
    if not label_change:
        return False
    prev = {l["title"] for l in label_change.get("previous", [])}
    curr = {l["title"] for l in label_change.get("current", [])}
    added = curr - prev
    iid = payload["object_attributes"]["iid"]
    for label in added:
        _trigger_pipeline(
            project_path=project_path,
            ref=payload["project"].get("default_branch", "main"),
            variables={
                "CI_TRIGGERED_EVENT": "issue_label_added",
                "SW_ISSUE_IID": str(iid),
                "SW_LABEL_ADDED": label,
            },
        )
        return True
    return False


def _maybe_trigger_note(payload: dict, project_path: str) -> bool:
    obj = payload.get("object_attributes", {})
    if obj.get("noteable_type") != "Issue":
        return False
    issue = payload.get("issue") or {}
    _trigger_pipeline(
        project_path=project_path,
        ref=payload["project"].get("default_branch", "main"),
        variables={
            "CI_TRIGGERED_EVENT": "issue_note_added",
            "SW_ISSUE_IID": str(issue.get("iid")),
            "SW_COMMENT_BODY": obj.get("note", ""),
        },
    )
    return True


def _maybe_trigger_mr(payload: dict, project_path: str) -> bool:
    changes = payload.get("changes", {})
    draft = changes.get("draft") or changes.get("work_in_progress")
    if not draft:
        return False
    if not (draft.get("previous") is True and draft.get("current") is False):
        return False
    iid = payload["object_attributes"]["iid"]
    _trigger_pipeline(
        project_path=project_path,
        ref=payload["project"].get("default_branch", "main"),
        variables={
            "CI_TRIGGERED_EVENT": "mr_ready",
            "SW_MR_IID": str(iid),
        },
    )
    return True


def _trigger_pipeline(*, project_path: str, ref: str, variables: dict[str, str]) -> None:
    gl = gitlab.Gitlab(
        url=os.environ.get("CI_SERVER_URL", "https://gitlab.com"),
        private_token=os.environ["GITLAB_API_TOKEN"],
    )
    project = gl.projects.get(project_path)
    project.pipelines.create(
        {
            "ref": ref,
            "variables": [{"key": k, "value": v} for k, v in variables.items()],
        }
    )


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8080)
```

- [ ] **Step 5: Run, confirm pass**

```bash
pytest tests/sw/test_webhook_relay.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/sw/webhook_relay.py tests/sw/test_webhook_relay.py pyproject.toml
git commit -m "feat(webhook_relay): translate GitLab webhooks to CI pipeline triggers"
```

---

## Task 18: End-to-End Smoke Test (Manual Procedure)

**Files:**
- Create: `docs/SMOKE_TEST.md`

Document the manual end-to-end walkthrough for MVP demonstration.

- [ ] **Step 1: Write `docs/SMOKE_TEST.md`**

````markdown
# Skeleton MVP Smoke Test

Verifies the end-to-end loop on GitLab CE.

## Prerequisites

- GitLab CE instance, version ≥ 16.0
- A test project, e.g. `agent-demo/test-repo`
- A Personal Access Token (or Project Access Token) with `api` scope
- A GitLab Runner registered to the project, allowed to run untagged jobs
- This framework repo cloned and installed in the Runner image (or pip-installable URL set as `SW_FRAMEWORK_GIT_URL`)
- `webhook_relay` service deployed (e.g., on the same host or a sidecar) and reachable from GitLab

## One-time Setup

1. **Configure project CI/CD Variables** (Settings → CI/CD → Variables):
   - `GITLAB_API_TOKEN` — value: your PAT, **Masked**, **Protected**
   - `SW_FRAMEWORK_GIT_URL` — URL of this repo (HTTPS clone URL)

2. **Apply labels**:

   ```bash
   export GITLAB_API_TOKEN=<your-token>
   python -m sw.label_apply --project agent-demo/test-repo --gitlab-url https://gitlab.example.com
   ```

3. **Install templates** in the project:

   - Copy `templates/issue_template.md` → `.gitlab/issue_templates/agent-task.md`
   - Copy `templates/mr_template.md` → `.gitlab/merge_request_templates/agent-mr.md`
   - Copy `ci/gitlab-ci.yml` → `.gitlab-ci.yml`
   - Commit and push to `main`.

4. **Deploy webhook relay**:

   ```bash
   export GITLAB_API_TOKEN=<your-token>
   export WEBHOOK_SECRET=<generate-strong-string>
   export CI_SERVER_URL=https://gitlab.example.com
   python -m sw.webhook_relay
   ```

5. **Configure project Webhook** (Settings → Webhooks):
   - URL: `http://<relay-host>:8080/webhook`
   - Secret token: `<WEBHOOK_SECRET>` from step 4
   - Triggers: ☑ Issues events, ☑ Comments, ☑ Merge request events

## Walkthrough

### Path 1: Happy Path

1. Create a new Issue using the `agent-task` template.
2. Fill the Issue body — include a non-empty AC block:

   ```markdown
   <!-- ac:start -->
   - When project is touched, AGENT_LOG.md exists at root.
   <!-- ac:end -->
   ```

3. Add the `agent-ready` label.
4. Within ~30 seconds, observe:
   - Label changes from `agent-ready` to `agent-working`.
   - A new branch `agent/issue-<iid>` appears.
   - A Draft MR is opened, closing this Issue.
5. Mark the MR as Ready (un-draft it).
6. Within ~30 seconds, observe:
   - Reviewer matrix runs (stub returns all PASS — visible in pipeline logs).
   - MR is rebased and ff-merged into `main`.
   - Issue label transitions to `agent-done`.
   - Issue is closed (because of `Closes #X`).

### Path 2: AC Missing

1. Create an Issue with the template but leave the `<!-- ac:start --><!-- ac:end -->` block empty.
2. Add the `agent-ready` label.
3. Within ~30 seconds, observe:
   - Label transitions to `needs-human`.
   - A comment appears on the Issue with the `🛑 需要人类决策` heading and a YAML block.
4. Edit the Issue to add valid AC.
5. Add a comment: `decision: edit_issue done` followed on a new line by `/agent resume`.
6. Within ~30 seconds, observe:
   - Label returns to `agent-working`.
   - Coder runs again; from here Path 1 continues from step 4.

### Path 3: Manual Abort

1. While an Agent is working, comment `/agent abort`.
2. Within ~30 seconds, observe:
   - Label transitions to `agent-failed`.
   - No further automation runs on this Issue.
````

- [ ] **Step 2: Commit**

```bash
git add docs/SMOKE_TEST.md
git commit -m "docs: smoke test procedure for skeleton MVP"
```

---

## Task 19: Final Coverage Run + Tag

- [ ] **Step 1: Run full test suite with coverage**

```bash
pytest --cov=sw --cov-report=term-missing
```

Expected: all tests pass; coverage ≥ 90% on files in `src/sw/` (handlers may be slightly lower due to side-effect-heavy code paths).

- [ ] **Step 2: Add a `Makefile` for common tasks**

`Makefile`:
```makefile
.PHONY: test cov lint

test:
	pytest

cov:
	pytest --cov=sw --cov-report=term-missing

lint:
	ruff check src tests

format:
	ruff format src tests
```

- [ ] **Step 3: Run lint, fix any issues**

```bash
make lint
make format
make test
```

Expected: no lint errors; tests pass.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "chore: add Makefile for common tasks"
```

- [ ] **Step 5: Tag the MVP**

```bash
git tag -a v0.1.0-mvp -m "Skeleton MVP: end-to-end loop with stub Coder/Reviewer on GitLab CE"
git log --oneline | head -25
```

---

## Acceptance Criteria for This Plan

This plan is "done" when:

1. ✅ All Tasks 1–19 are completed and committed
2. ✅ `pytest` passes with ≥ 90% coverage on `src/sw/`
3. ✅ `docs/SMOKE_TEST.md` Path 1 (happy path) is verified end-to-end on a real GitLab CE instance
4. ✅ `docs/SMOKE_TEST.md` Path 2 (AC missing → resume) is verified end-to-end
5. ✅ `docs/SMOKE_TEST.md` Path 3 (manual abort) is verified end-to-end
6. ✅ Linear git history (rebase + ff-merge convention) is preserved on the framework repo

## Out of Scope (Future Plans)

- Real Coder Agent (replaces stub) — separate plan
- Real Reviewer Agents (7 dimensions, replace stub) — separate plan
- Merge Queue (replaces direct ff-merge) — separate plan
- GitHub + Copilot adapter — separate plan
- Observability (metrics, dashboards) — separate plan
- Failure-loop counter / circuit breaker for needs-human — defer to real Agent plan
