import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sw.copilot_cli_client import CopilotCliClient, CopilotCliError, CopilotCliResult


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["copilot"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# Tests pass stream=False to use the subprocess.run code path (patchable).
# A separate test below covers the default streaming code path.


def test_run_passes_prompt_to_subprocess(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed()) as mock_run:
        client.run(prompt="hello", cwd=tmp_path, stream=False)
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "copilot"
    assert "--prompt" in cmd
    assert "hello" in cmd
    assert "--allow-all" in cmd
    assert kwargs["cwd"] == tmp_path


def test_run_passes_env(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed()) as mock_run:
        client.run(prompt="x", cwd=tmp_path, env={"GITHUB_TOKEN": "tk"}, stream=False)
    env = mock_run.call_args.kwargs["env"]
    assert env["GITHUB_TOKEN"] == "tk"


def test_run_returns_result(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed(stdout="x", stderr="y")):
        result = client.run(prompt="x", cwd=tmp_path, stream=False)
    assert isinstance(result, CopilotCliResult)
    assert result.returncode == 0
    assert result.stdout == "x"
    assert result.stderr == "y"


def test_run_raises_on_nonzero_when_check_true(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed(returncode=1, stderr="boom")):
        with pytest.raises(CopilotCliError, match="boom"):
            client.run(prompt="x", cwd=tmp_path, check=True, stream=False)


def test_run_returns_nonzero_when_check_false(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed(returncode=2)):
        result = client.run(prompt="x", cwd=tmp_path, check=False, stream=False)
    assert result.returncode == 2


def test_run_with_log_dir_writes_artifacts(tmp_path: Path):
    """log_dir gets stdout/stderr/exit-code files."""
    client = CopilotCliClient(executable="copilot")
    log_dir = tmp_path / "logs"
    with patch("subprocess.run", return_value=_completed(returncode=7, stdout="OUT", stderr="ERR")):
        client.run(prompt="x", cwd=tmp_path, log_dir=log_dir, stream=False)
    assert (log_dir / "copilot-stdout.log").read_text() == "OUT"
    assert (log_dir / "copilot-stderr.log").read_text() == "ERR"
    assert (log_dir / "exit-code.txt").read_text() == "7"


def test_run_streaming_path(tmp_path: Path):
    """Default stream=True uses run_streaming helper (patched here)."""
    client = CopilotCliClient(executable="copilot")
    with patch(
        "sw.copilot_cli_client.run_streaming",
        return_value=(0, "stdout-content", "stderr-content"),
    ) as mock_stream:
        result = client.run(prompt="x", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout == "stdout-content"
    assert result.stderr == "stderr-content"
    args, kwargs = mock_stream.call_args
    assert "[copilot] " == kwargs["stdout_prefix"]
