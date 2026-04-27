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


def test_run_passes_prompt_to_subprocess(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed()) as mock_run:
        client.run(prompt="hello", cwd=tmp_path)
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
        client.run(prompt="x", cwd=tmp_path, env={"GITHUB_TOKEN": "tk"})
    env = mock_run.call_args.kwargs["env"]
    assert env["GITHUB_TOKEN"] == "tk"


def test_run_returns_result(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed(stdout="x", stderr="y")):
        result = client.run(prompt="x", cwd=tmp_path)
    assert isinstance(result, CopilotCliResult)
    assert result.returncode == 0
    assert result.stdout == "x"
    assert result.stderr == "y"


def test_run_raises_on_nonzero_when_check_true(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed(returncode=1, stderr="boom")):
        with pytest.raises(CopilotCliError, match="boom"):
            client.run(prompt="x", cwd=tmp_path, check=True)


def test_run_returns_nonzero_when_check_false(tmp_path: Path):
    client = CopilotCliClient(executable="copilot")
    with patch("subprocess.run", return_value=_completed(returncode=2)):
        result = client.run(prompt="x", cwd=tmp_path, check=False)
    assert result.returncode == 2
