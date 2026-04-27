"""Subprocess wrapper for the `claude` CLI (Claude Code)."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sw._subprocess_streaming import run_streaming


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
        log_dir: Path | None = None,
        log_level: str = "debug",
        stream: bool = True,
    ) -> ClaudeCodeResult:
        """Invoke `claude --print` non-interactively.

        With `stream=True` (default), stdout/stderr are tee'd to console while
        being captured. `stream=False` falls back to `subprocess.run` (for tests
        that patch `subprocess.run`).
        """
        merged_env = {**os.environ, **(env or {})}
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            merged_env.setdefault("CLAUDE_LOG_LEVEL", log_level)

        if stream:
            returncode, stdout, stderr = run_streaming(
                [self.executable, "--print"],
                cwd=cwd,
                env=merged_env,
                timeout=timeout,
                input_data=prompt,
                stdout_prefix="[claude] ",
                stderr_prefix="[claude:err] ",
            )
        else:
            proc = subprocess.run(
                [self.executable, "--print"],
                input=prompt,
                cwd=cwd,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr

        if log_dir is not None:
            (log_dir / "claude-stdout.log").write_text(stdout or "")
            (log_dir / "claude-stderr.log").write_text(stderr or "")
            (log_dir / "exit-code.txt").write_text(str(returncode))

        if check and returncode != 0:
            raise ClaudeCodeError(stderr or f"exit {returncode}")
        return ClaudeCodeResult(returncode=returncode, stdout=stdout, stderr=stderr)
