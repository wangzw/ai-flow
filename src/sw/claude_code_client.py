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
