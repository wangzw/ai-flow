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
        client.run(prompt="hello", cwd=tmp_path, stream=False)
    args, kwargs = mock_run.call_args
    assert args[0][0] == "claude"
    assert "--print" in args[0]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["input"] == "hello"


def test_run_passes_env(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed()) as mock_run:
        client.run(prompt="x", cwd=tmp_path, env={"ANTHROPIC_API_KEY": "k"}, stream=False)
    env = mock_run.call_args.kwargs["env"]
    assert env["ANTHROPIC_API_KEY"] == "k"


def test_run_returns_result_with_stdout_and_returncode(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed(stdout="output text")):
        result = client.run(prompt="x", cwd=tmp_path, stream=False)
    assert isinstance(result, ClaudeCodeResult)
    assert result.returncode == 0
    assert result.stdout == "output text"


def test_run_raises_on_nonzero_when_check_true(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed(returncode=1, stderr="boom")):
        with pytest.raises(ClaudeCodeError, match="boom"):
            client.run(prompt="x", cwd=tmp_path, check=True, stream=False)


def test_run_returns_nonzero_when_check_false(tmp_path: Path):
    client = ClaudeCodeClient(executable="claude")
    with patch("subprocess.run", return_value=_completed(returncode=2, stderr="err")):
        result = client.run(prompt="x", cwd=tmp_path, check=False, stream=False)
    assert result.returncode == 2
    assert "err" in result.stderr


def test_run_streaming_path(tmp_path: Path):
    """Default stream=True uses run_streaming helper (patched here)."""
    client = ClaudeCodeClient(executable="claude")
    with patch(
        "sw.claude_code_client.run_streaming",
        return_value=(0, "stdout-content", "stderr-content"),
    ) as mock_stream:
        result = client.run(prompt="x", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout == "stdout-content"
    args, kwargs = mock_stream.call_args
    assert kwargs["input_data"] == "x"
    assert "[claude] " == kwargs["stdout_prefix"]
