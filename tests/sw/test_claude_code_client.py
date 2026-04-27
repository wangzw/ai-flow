import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sw.claude_code_client import ClaudeCodeClient, ClaudeCodeError, ClaudeCodeResult


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
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
