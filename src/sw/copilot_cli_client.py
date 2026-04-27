"""Subprocess wrapper for the `copilot` CLI (GitHub Copilot CLI).

API parity with `claude_code_client.ClaudeCodeClient` so that Coder/Reviewer
modules can swap GitHub for GitLab by changing the injected client.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class CopilotCliError(RuntimeError):
    """Raised when copilot subprocess exits non-zero with check=True."""


@dataclass(frozen=True)
class CopilotCliResult:
    returncode: int
    stdout: str
    stderr: str


class CopilotCliClient:
    def __init__(self, executable: str = "copilot"):
        self.executable = executable

    def run(
        self,
        *,
        prompt: str,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int = 1800,
        check: bool = False,
    ) -> CopilotCliResult:
        """Invoke `copilot` non-interactively with --prompt and --allow-all.

        Per `copilot --help`:
        - `-p/--prompt <text>` runs in non-interactive mode
        - `--allow-all` enables tools/paths/URLs (required for non-interactive)
        """
        merged_env = {**os.environ, **(env or {})}
        proc = subprocess.run(
            [self.executable, "--prompt", prompt, "--allow-all"],
            cwd=cwd,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise CopilotCliError(proc.stderr or f"exit {proc.returncode}")
        return CopilotCliResult(
            returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
        )
