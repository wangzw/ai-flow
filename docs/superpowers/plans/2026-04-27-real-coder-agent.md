# Real Coder Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace `coder_stub.py` with a real Coder Agent that uses **Claude Code CLI** to read an Issue's AC, clone the target repo, iterate locally until tests pass, commit code (with WHY-comments), and open a draft MR. Failures (AC ambiguity, irrecoverable errors) yield structured `needs-human` comments.

**Architecture:**
- New module `claude_code_client.py` wraps the `claude` CLI as subprocess
- New module `coder.py` orchestrates: clone → prepare prompt → invoke Claude Code → parse result → commit → open MR
- Stub `coder_stub.py` is **kept** but renamed to `coder_fake.py` (test-only fake)
- Handlers updated to import `run_coder` from `coder` (real) by default
- Subprocess + filesystem operations are mocked in unit tests; integration tests are skipped by default

**Tech Stack:** Python 3.11+, subprocess, tempfile, GitPython (NEW dep), pytest, ruamel.yaml

**Spec source:** `docs/superpowers/specs/2026-04-27-ai-coding-workflow-design.md`

---

## DECISIONS (defaults; flag if you disagree)

1. **Claude Code invocation mode**: Non-interactive `--print` mode with prompt streamed via stdin. Single-shot execution; if Claude Code can't finish in one session, it returns BLOCKED. (Alternative: multi-turn — defer to future plan.)
2. **Working directory**: Coder clones the target project into a temp dir on the Runner, runs Claude Code there, then pushes via git CLI to the agent branch. Avoids relying on `python-gitlab` for individual file commits (current stub uses `commits.create` API which can't run tests locally).
3. **Test execution**: Coder relies on Claude Code itself to run/iterate tests. We give Claude Code the project + AC and let it figure out the test framework.
4. **Output protocol**: Claude Code writes a final structured marker to a known file (`.agent/result.yaml`) before exiting. Marker indicates `status: done | blocked` plus reason/decision payload. Coder parses this file.
5. **Code-comment WHY enforcement**: Spec §5.3 says Coder must write non-obvious WHY into code comments. We enforce this via the prompt instruction; Reviewer matrix verifies post-hoc.
6. **Failure → `needs-human`**: When Claude Code returns BLOCKED, Coder posts a structured comment via existing `comment_writer` and the calling handler transitions state. (Coder itself does not change labels; it returns a `CoderResult` with `success=False` + `blocker` payload, and the handler does the transition.)
7. **`coder_stub.py` fate**: Renamed to `coder_fake.py`, kept for unit tests that need a fake (so handler tests don't have to mock subprocess).

---

## Repository Layout (after this plan)

```
src/sw/
├── claude_code_client.py    NEW
├── coder.py                 NEW (real implementation)
├── coder_fake.py            RENAMED from coder_stub.py (test fake)
└── handlers/                  (updated imports)
tests/sw/
├── test_claude_code_client.py  NEW
├── test_coder.py            NEW (extends old test_coder_stub coverage)
└── handlers/                  (existing tests use coder_fake)
```

---

## Task 1: Add `gitpython` dep + scaffold module skeletons

**Files:**
- Modify: `pyproject.toml`
- Create: `src/sw/claude_code_client.py` (empty stub with module docstring)
- Create: `src/sw/coder.py` (empty stub with module docstring)

- [ ] **Step 1: Add gitpython to deps**

Edit `pyproject.toml` `dependencies` list:
```toml
dependencies = [
    "python-gitlab>=4.4.0",
    "ruamel.yaml>=0.18.0",
    "flask>=3.0",
    "gitpython>=3.1",
]
```

Run: `.venv/bin/pip install -e ".[dev]"`

- [ ] **Step 2: Create empty modules**

`src/sw/claude_code_client.py`:
```python
"""Subprocess wrapper for the `claude` CLI (Claude Code).

Provides non-interactive invocation with streamed stdin prompts and
structured result parsing.
"""
```

`src/sw/coder.py`:
```python
"""Real Coder Agent: orchestrates Claude Code to implement an Issue's AC.

Workflow:
1. Clone the target project into a temp dir.
2. Build a prompt from Issue body + AC + project context.
3. Invoke Claude Code (via claude_code_client).
4. Parse the result marker file.
5. On success: stage commits, push to agent branch, open draft MR.
6. On block: return CoderResult(success=False, blocker=...).
"""
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml src/sw/claude_code_client.py src/sw/coder.py
git commit -m "chore(coder): add gitpython dep and scaffold real coder modules"
```

---

## Task 2: `ClaudeCodeClient` — subprocess wrapper

**Files:**
- Modify: `src/sw/claude_code_client.py`
- Create: `tests/sw/test_claude_code_client.py`

The client invokes `claude --print --output-format stream-json` (or similar non-interactive mode) with a prompt, in a working directory, with environment variables (incl. `ANTHROPIC_API_KEY`). Returns parsed result.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_claude_code_client.py`:
```python
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from sw.claude_code_client import ClaudeCodeClient, ClaudeCodeError, ClaudeCodeResult


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_run_passes_prompt_to_subprocess(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed()) as mock_run:
        client.run(prompt="hello", cwd=tmp_path)
    args, kwargs = mock_run.call_args
    assert args[0][0] == "claude"
    assert "--print" in args[0]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["input"] == "hello"


def test_run_passes_env(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed()) as mock_run:
        client.run(prompt="x", cwd=tmp_path, env={"ANTHROPIC_API_KEY": "k"})
    env = mock_run.call_args.kwargs["env"]
    assert env["ANTHROPIC_API_KEY"] == "k"


def test_run_returns_result_with_stdout_and_returncode(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed(stdout="output text")):
        result = client.run(prompt="x", cwd=tmp_path)
    assert isinstance(result, ClaudeCodeResult)
    assert result.returncode == 0
    assert result.stdout == "output text"


def test_run_raises_on_nonzero_when_check_true(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed(returncode=1, stderr="boom")):
        with pytest.raises(ClaudeCodeError, match="boom"):
            client.run(prompt="x", cwd=tmp_path, check=True)


def test_run_returns_nonzero_when_check_false(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed(returncode=2, stderr="err")):
        result = client.run(prompt="x", cwd=tmp_path, check=False)
    assert result.returncode == 2
    assert "err" in result.stderr
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/sw/test_claude_code_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement client**

Replace `src/sw/claude_code_client.py` with:
```python
"""Subprocess wrapper for the `claude` CLI (Claude Code)."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ClaudeCodeError(RuntimeError):
    """Raised when Claude Code subprocess exits non-zero with check=True."""


@dataclass(frozen=True)
class ClaudeCodeResult:
    returncode: int
    stdout: str
    stderr: str


class ClaudeCodeClient:
    def __init__(self, executable: str = "claude"):
        self.executable = executable

    def run(
        self,
        *,
        prompt: str,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int = 1800,
        check: bool = False,
    ) -> ClaudeCodeResult:
        """Invoke claude --print non-interactively, streaming prompt via stdin."""
        merged_env = {**os.environ, **(env or {})}
        proc = subprocess.run(
            [self.executable, "--print"],
            input=prompt,
            cwd=cwd,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise ClaudeCodeError(proc.stderr or f"exit {proc.returncode}")
        return ClaudeCodeResult(
            returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
        )
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
.venv/bin/pytest tests/sw/test_claude_code_client.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check --fix src tests
git add src/sw/claude_code_client.py tests/sw/test_claude_code_client.py
git commit -m "feat(claude_code_client): subprocess wrapper for claude CLI"
```

---

## Task 3: Rename `coder_stub.py` → `coder_fake.py`; update handler imports

**Files:**
- Rename: `src/sw/coder_stub.py` → `src/sw/coder_fake.py`
- Rename: `tests/sw/test_coder_stub.py` → `tests/sw/test_coder_fake.py`
- Modify: `src/sw/handlers/issue_handler.py`
- Modify: `src/sw/handlers/comment_handler.py`

The fake is kept for handler tests (so they don't have to mock subprocess). The real `coder.py` will be implemented in Task 4.

- [ ] **Step 1: Rename files via git**

```bash
git mv src/sw/coder_stub.py src/sw/coder_fake.py
git mv tests/sw/test_coder_stub.py tests/sw/test_coder_fake.py
```

- [ ] **Step 2: Update internal imports in renamed files**

Edit `tests/sw/test_coder_fake.py`: change `from sw.coder_stub import ...` → `from sw.coder_fake import ...` (use Edit tool).

- [ ] **Step 3: Update handler imports temporarily to keep tests passing**

The handlers currently import from `coder_stub`. Until `coder.py` exists with `run_coder`, point them at `coder_fake`:

In `src/sw/handlers/issue_handler.py`: change `from sw.coder_stub import run_coder` → `from sw.coder_fake import run_coder`.
In `src/sw/handlers/comment_handler.py`: same.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest -q
```

Expected: same count as before (after Task 2: 73 passed = 68 + 5 new). All previous tests still pass.

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff check --fix src tests
git add -A
git commit -m "refactor(coder): rename coder_stub to coder_fake; handlers import from fake"
```

---

## Task 4: Real Coder — `coder.py`

**Files:**
- Modify: `src/sw/coder.py`
- Create: `tests/sw/test_coder.py`

The real Coder:
1. Receives `(project, issue_iid, issue_title)`.
2. Clones the project to a temp dir at the agent branch (creates branch if needed).
3. Reads Issue body via `project.issues.get(iid)`.
4. Builds a prompt with Issue title + body + AC.
5. Invokes Claude Code in the temp dir.
6. Reads the result marker file `.agent/result.yaml`.
7. On `status: done`: pushes the branch, opens a draft MR.
8. On `status: blocked`: returns CoderResult(success=False, blocker=...) — handler will post comment & transition state.

- [ ] **Step 1: Write failing tests**

`tests/sw/test_coder.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sw.coder import run_coder, CoderResult


@pytest.fixture
def fake_project():
    project = MagicMock()
    project.default_branch = "main"
    project.path_with_namespace = "g/r"
    project.http_url_to_repo = "https://gitlab.example/g/r.git"
    issue = MagicMock()
    issue.description = "## AC\n<!-- ac:start -->\nDo X\n<!-- ac:end -->"
    issue.title = "test"
    project.issues.get.return_value = issue
    mr = MagicMock()
    mr.iid = 100
    project.mergerequests.create.return_value = mr
    return project


def test_run_coder_done_creates_mr(fake_project, tmp_path):
    """Happy path: Claude Code returns done; coder pushes & opens MR."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        result_dir = Path(to_path) / ".agent"
        result_dir.mkdir()
        (result_dir / "result.yaml").write_text("status: done\nsummary: implemented X\n")
        return MagicMock()

    fake_repo = MagicMock()
    fake_repo.head.commit.hexsha = "abc123"
    with patch("sw.coder._clone_repo", side_effect=fake_clone) as clone, \
         patch("sw.coder._push_branch") as push:
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is True
    assert result.mr_iid == 100
    cc.run.assert_called_once()
    push.assert_called_once()
    fake_project.mergerequests.create.assert_called_once()


def test_run_coder_blocked_returns_blocker(fake_project, tmp_path):
    """Claude Code marker says blocked → no MR, blocker payload returned."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        result_dir = Path(to_path) / ".agent"
        result_dir.mkdir()
        (result_dir / "result.yaml").write_text(
            "status: blocked\n"
            "blocker_type: ac_ambiguity\n"
            "question: 'How to handle X?'\n"
            "options:\n"
            "  - id: a\n"
            "  - id: b\n"
        )
        return MagicMock()

    with patch("sw.coder._clone_repo", side_effect=fake_clone), \
         patch("sw.coder._push_branch"):
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is False
    assert result.blocker is not None
    assert result.blocker["blocker_type"] == "ac_ambiguity"
    fake_project.mergerequests.create.assert_not_called()


def test_run_coder_subprocess_error_returns_blocker(fake_project, tmp_path):
    """Claude Code subprocess error → blocker."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=1, stdout="", stderr="rate limit")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        return MagicMock()

    with patch("sw.coder._clone_repo", side_effect=fake_clone), \
         patch("sw.coder._push_branch"):
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is False
    assert result.blocker["blocker_type"] == "subprocess_error"


def test_run_coder_missing_marker_returns_blocker(fake_project, tmp_path):
    """No marker file written → blocker."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        return MagicMock()

    with patch("sw.coder._clone_repo", side_effect=fake_clone), \
         patch("sw.coder._push_branch"):
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is False
    assert result.blocker["blocker_type"] == "no_result_marker"
```

- [ ] **Step 2: Run, confirm failure**

```bash
.venv/bin/pytest tests/sw/test_coder.py -v
```

Expected: ImportError (run_coder, CoderResult not yet in `coder.py`).

- [ ] **Step 3: Implement Coder**

Replace `src/sw/coder.py` with:
```python
"""Real Coder Agent: orchestrates Claude Code to implement an Issue's AC."""

import shutil
import tempfile
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from sw.claude_code_client import ClaudeCodeClient


@dataclass(frozen=True)
class CoderResult:
    success: bool
    mr_iid: int | None = None
    branch_name: str = ""
    blocker: dict | None = None  # populated when success=False


_PROMPT_TEMPLATE = """You are an autonomous coding agent implementing an Issue's AC.

Project root: {cwd}
Issue title: {title}
Issue body:
---
{body}
---

Your task:
1. Read the AC block in the Issue body (between <!-- ac:start --> and <!-- ac:end -->).
2. Implement the requested change in this project. Follow existing patterns and conventions.
3. Write tests covering each AC item before implementation (TDD).
4. For any non-obvious WHY (constraints, workarounds, invariants), add a code comment — this is the only channel reviewers will see your reasoning. Commit messages will NOT be read by reviewers.
5. Iterate until all tests pass locally.
6. Stage all changes and commit them with a clear message.

When done — and ONLY when all tests pass and code is committed — write a result marker:

  mkdir -p .agent
  cat > .agent/result.yaml <<'EOF'
  status: done
  summary: <one-line summary of what you did>
  EOF

If you cannot proceed (AC ambiguous, conflict requires human decision, missing context):

  mkdir -p .agent
  cat > .agent/result.yaml <<'EOF'
  status: blocked
  blocker_type: <ac_ambiguity | conflict | needs_choice | other>
  question: <human-readable question>
  options:
    - id: <id>
      desc: <description>
  EOF

Then exit. Do NOT proceed past blocked.
"""


def _clone_repo(url: str, to_path: Path, branch: str | None = None):
    """Wrapper around git clone to allow patching in tests."""
    from git import Repo

    if branch:
        return Repo.clone_from(url, to_path, branch=branch)
    return Repo.clone_from(url, to_path)


def _push_branch(repo, branch_name: str):
    """Push the agent branch upstream. Patchable in tests."""
    repo.git.push("--set-upstream", "origin", branch_name)


def _read_result(workdir: Path) -> dict | None:
    marker = workdir / ".agent" / "result.yaml"
    if not marker.exists():
        return None
    yaml = YAML(typ="safe")
    try:
        return yaml.load(StringIO(marker.read_text()))
    except Exception:
        return None


def run_coder(
    *,
    project,
    issue_iid: int,
    issue_title: str,
    claude: ClaudeCodeClient | None = None,
    workdir: Path | None = None,
) -> CoderResult:
    """Run real Coder: clone, prompt Claude Code, parse result, push & open MR.

    `claude` and `workdir` are injectable for testing.
    """
    claude = claude or ClaudeCodeClient()
    workdir = workdir or Path(tempfile.mkdtemp(prefix=f"agent-issue-{issue_iid}-"))
    branch_name = f"agent/issue-{issue_iid}"
    base = project.default_branch

    issue = project.issues.get(issue_iid)
    body = issue.description or ""

    repo_path = workdir / "repo"
    try:
        repo = _clone_repo(project.http_url_to_repo, repo_path, branch=base)
    except Exception as exc:
        return CoderResult(
            success=False,
            blocker={"blocker_type": "clone_failed", "reason": str(exc)},
            branch_name=branch_name,
        )

    # New branch for the agent's work
    try:
        repo.git.checkout("-b", branch_name)
    except Exception:
        pass  # may already exist; ignore

    prompt = _PROMPT_TEMPLATE.format(cwd=str(repo_path), title=issue_title, body=body)

    cc_result = claude.run(prompt=prompt, cwd=repo_path)
    if cc_result.returncode != 0:
        return CoderResult(
            success=False,
            blocker={
                "blocker_type": "subprocess_error",
                "stderr": cc_result.stderr[-2000:],
                "returncode": cc_result.returncode,
            },
            branch_name=branch_name,
        )

    marker = _read_result(repo_path)
    if marker is None:
        return CoderResult(
            success=False,
            blocker={"blocker_type": "no_result_marker"},
            branch_name=branch_name,
        )

    if marker.get("status") == "blocked":
        return CoderResult(
            success=False,
            blocker={
                "blocker_type": marker.get("blocker_type", "unknown"),
                "question": marker.get("question", ""),
                "options": marker.get("options", []),
            },
            branch_name=branch_name,
        )

    if marker.get("status") != "done":
        return CoderResult(
            success=False,
            blocker={"blocker_type": "unknown_status", "raw": marker},
            branch_name=branch_name,
        )

    # Done — push & open MR
    _push_branch(repo, branch_name)

    mr = project.mergerequests.create(
        {
            "source_branch": branch_name,
            "target_branch": base,
            "title": f"Draft: {issue_title}",
            "description": (
                f"Auto-generated by Coder Agent for issue #{issue_iid}.\n\n"
                f"Closes #{issue_iid}\n\n"
                f"Summary: {marker.get('summary', '')}"
            ),
            "remove_source_branch": True,
        }
    )

    return CoderResult(success=True, mr_iid=mr.iid, branch_name=branch_name)
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
.venv/bin/pytest tests/sw/test_coder.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Update handler imports back to real `coder`**

Now that `coder.py` provides `run_coder`, update handlers:

`src/sw/handlers/issue_handler.py`: change `from sw.coder_fake import run_coder` → `from sw.coder import run_coder`.
`src/sw/handlers/comment_handler.py`: same.

Run handler tests — they pass `coder=` injected fakes, so they don't depend on the real subprocess. They should still pass:

```bash
.venv/bin/pytest tests/sw/handlers -v
```

Expected: all handler tests pass.

- [ ] **Step 6: Run full suite + lint + commit**

```bash
.venv/bin/pytest -q     # expect 77 passed (73 + 4 new)
.venv/bin/ruff check --fix src tests
git add -A
git commit -m "feat(coder): real coder agent using Claude Code CLI"
```

---

## Task 5: Wire Coder failure path through `issue_handler`

**Files:**
- Modify: `src/sw/handlers/issue_handler.py`
- Modify: `tests/sw/handlers/test_issue_handler.py`

When the real Coder returns `success=False` with a `blocker` payload, the handler should post a `needs-human` comment using `comment_writer` and transition the Issue label to `needs-human`. (The `agent-working` label was already set before invoking the coder.)

- [ ] **Step 1: Add failing test**

Append to `tests/sw/handlers/test_issue_handler.py`:
```python
def test_coder_returns_blocker_transitions_to_needs_human():
    project = MagicMock()
    issue = _make_issue(body=VALID_BODY, labels=["agent-ready"])
    project.issues.get.return_value = issue

    blocker = {
        "blocker_type": "ac_ambiguity",
        "question": "How?",
        "options": [{"id": "a", "desc": "A"}],
    }
    coder = MagicMock(
        return_value=MagicMock(success=False, mr_iid=None, blocker=blocker)
    )
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
    # First transition agent-working then needs-human
    assert labels_set == ["agent-working", "needs-human"]
    client.comment_on_issue.assert_called_once()
    body = client.comment_on_issue.call_args[0][1]
    assert "How?" in body  # the blocker question is surfaced
```

- [ ] **Step 2: Run, confirm failure**

Expected: AssertionError — handler currently ignores blocker.

- [ ] **Step 3: Modify handler**

Edit `src/sw/handlers/issue_handler.py`. Replace the final two lines of `handle_issue_event`:

```python
    client.set_state_label(issue, "agent-working")
    coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
```

with:

```python
    client.set_state_label(issue, "agent-working")
    result = coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
    if result is None or result.success:
        return
    blocker = result.blocker or {}
    comment = build_needs_human_comment(
        prose=f"Coder 阻塞：{blocker.get('blocker_type', 'unknown')}",
        agent_state={
            "stage": "coder",
            "blocker_type": blocker.get("blocker_type", "unknown"),
        },
        decision={
            "question": blocker.get("question", "请人工决策"),
            "options": blocker.get("options", []),
            "custom_allowed": True,
        },
    )
    client.comment_on_issue(issue, comment)
    client.set_state_label(issue, "needs-human")
```

- [ ] **Step 4: Run, confirm pass + lint + commit**

```bash
.venv/bin/pytest tests/sw/handlers/test_issue_handler.py -v   # expect 4 passed
.venv/bin/pytest -q                                            # expect 78 passed
.venv/bin/ruff check --fix src tests
git add -A
git commit -m "feat(issue_handler): post needs-human comment on coder blocker"
```

Note: `comment_handler` also calls coder for resume/retry — same blocker handling should apply there. Add similar test + change.

- [ ] **Step 5: Mirror for comment_handler — add test + handler change**

Append to `tests/sw/handlers/test_comment_handler.py`:
```python
def test_resume_with_coder_blocker_transitions_to_needs_human():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["needs-human"])
    client = MagicMock()
    coder = MagicMock(
        return_value=MagicMock(
            success=False,
            blocker={"blocker_type": "conflict", "question": "merge conflict"},
        )
    )

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="ok\n/agent resume",
        client=client,
        coder=coder,
    )

    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    # First moves to working then back to needs-human
    assert labels == ["agent-working", "needs-human"]
```

Update `src/sw/handlers/comment_handler.py`:
- Import `build_needs_human_comment`
- Change the final dispatch block to capture the result and post comment + transition on blocker:

```python
    if cmd in ("resume", "retry"):
        coder = coder or (lambda **kw: run_coder(**kw))
        result = coder(project=project, issue_iid=issue_iid, issue_title=issue.title)
        if result is not None and not result.success:
            blocker = result.blocker or {}
            comment = build_needs_human_comment(
                prose=f"Coder 再次阻塞：{blocker.get('blocker_type', 'unknown')}",
                agent_state={
                    "stage": "coder",
                    "blocker_type": blocker.get("blocker_type", "unknown"),
                },
                decision={
                    "question": blocker.get("question", "请人工决策"),
                    "options": blocker.get("options", []),
                    "custom_allowed": True,
                },
            )
            client.comment_on_issue(issue, comment)
            client.set_state_label(issue, "needs-human")
```

- [ ] **Step 6: Run, confirm pass + commit**

```bash
.venv/bin/pytest -q   # expect 79 passed
.venv/bin/ruff check --fix src tests
git add -A
git commit -m "feat(comment_handler): post needs-human comment on coder blocker"
```

---

## Task 6: CI image — install Claude Code

**Files:**
- Modify: `ci/gitlab-ci.yml`

Real Coder needs `claude` CLI on the Runner. Update CI to install it (and Node.js).

- [ ] **Step 1: Edit CI default image's before_script**

In `ci/gitlab-ci.yml`, change the default `before_script` from:

```yaml
  before_script:
    - pip install --quiet python-gitlab ruamel.yaml
    - pip install --quiet -e "git+${SW_FRAMEWORK_GIT_URL}@${SW_FRAMEWORK_REF:-main}#egg=software-workflow"
```

to:

```yaml
  before_script:
    - apt-get update -qq && apt-get install -y -qq curl git nodejs npm
    - npm install -g @anthropic-ai/claude-code
    - pip install --quiet python-gitlab ruamel.yaml gitpython flask
    - pip install --quiet -e "git+${SW_FRAMEWORK_GIT_URL}@${SW_FRAMEWORK_REF:-main}#egg=software-workflow"
    - 'echo "ANTHROPIC_API_KEY length: ${#ANTHROPIC_API_KEY}"'
```

Document that `ANTHROPIC_API_KEY` must be added to project CI/CD Variables (Masked, Protected) for the real Coder to function.

- [ ] **Step 2: Update README quick-start**

Edit `README.md`: in the Quick start section, between step 2 and 3, add:

```markdown
2.5. 在项目 CI/CD Variables 中添加 `ANTHROPIC_API_KEY`（Masked, Protected）—— 实 Coder 调 Claude Code 时使用
```

- [ ] **Step 3: Commit**

```bash
git add ci/gitlab-ci.yml README.md
git commit -m "chore(ci): install Claude Code in runner; document ANTHROPIC_API_KEY"
```

---

## Task 7: Update SMOKE_TEST.md

**Files:**
- Modify: `docs/SMOKE_TEST.md`

Add a section about the real Coder requirements + a Path 4 (real Coder happy path).

- [ ] **Step 1: Edit SMOKE_TEST.md**

Append a new section after Path 3:

```markdown
### Path 4: Real Coder (happy)

> **Prerequisite**: `ANTHROPIC_API_KEY` set in project CI/CD Variables.

1. Create an Issue with a clear, narrowly-scoped AC, e.g.:

   ```markdown
   <!-- ac:start -->
   - Add a function `hello()` in `src/greeting.py` that returns `"hello, world"`.
   - Add a test asserting `hello() == "hello, world"`.
   <!-- ac:end -->
   ```

2. Add `agent-ready` label.
3. Within ~5–10 minutes (Claude Code time), observe:
   - Agent branch contains a real commit implementing `hello()` and a test.
   - Draft MR opens with summary in description.
   - Reviewer matrix runs (still stub at this stage; replaced in Plan 3).
4. If Coder gets blocked, observe `needs-human` label + structured comment with the blocker.
```

- [ ] **Step 2: Commit**

```bash
git add docs/SMOKE_TEST.md
git commit -m "docs: smoke test path for real coder"
```

---

## Task 8: Final coverage + tag

- [ ] **Step 1: Coverage check**

```bash
.venv/bin/pytest --cov=sw --cov-report=term-missing
```

Expected: ≥ 88% (some new code paths involve real subprocess/git calls that are intentionally not covered by unit tests; integration tests deferred).

- [ ] **Step 2: Tag**

```bash
git tag -a v0.2.0-real-coder -m "Real Coder Agent using Claude Code CLI"
```

---

## Acceptance Criteria

- All 8 tasks done & committed
- 79+ tests pass; coverage ≥ 88%
- ruff clean
- `coder.py` correctly orchestrates clone → claude → marker parse → push & MR
- Both handlers post `needs-human` comments on Coder blocker
- CI image installs Claude Code; `ANTHROPIC_API_KEY` documented
- Tag `v0.2.0-real-coder` at HEAD

## Out of Scope (future)

- Multi-turn Coder (currently single-shot; if blocked once, requires human resume)
- Real git CLI vs python-gitlab API for branch creation (current design clones + pushes)
- Adaptive prompts based on past Coder failures
- Coder running in dedicated Docker image (currently uses CI's image)
