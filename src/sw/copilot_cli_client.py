"""Subprocess wrapper for the `copilot` CLI (GitHub Copilot CLI).

API parity with `claude_code_client.ClaudeCodeClient` so that Coder/Reviewer
modules can swap GitHub for GitLab by changing the injected client.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sw._subprocess_streaming import run_streaming_pty


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
        log_dir: Path | None = None,
        log_level: str = "debug",
        stream: bool = True,
    ) -> CopilotCliResult:
        """Invoke `copilot` non-interactively with --prompt and --allow-all.

        Per `copilot --help`:
        - `-p/--prompt <text>` runs in non-interactive mode
        - `--allow-all` enables tools/paths/URLs (required for non-interactive)
        - `--log-dir` + `--log-level` capture full session logs

        With `stream=True` (default), stdout/stderr are tee'd line-by-line to the
        parent's console as they arrive AND captured for the result. With
        `stream=False`, behaviour falls back to capture-only via `subprocess.run`
        (kept for tests that patch `subprocess.run`).
        """
        cmd = [self.executable, "--prompt", prompt, "--allow-all"]
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--log-dir", str(log_dir), "--log-level", log_level])

        merged_env = {**os.environ, **(env or {})}

        if stream:
            # PTY mode is the only reliable way to get real-time output from
            # `copilot` on non-TTY environments like GitHub Actions runners.
            # stdout and stderr are merged in PTY mode; stderr returned empty.
            returncode, stdout, stderr = run_streaming_pty(
                cmd,
                cwd=cwd,
                env=merged_env,
                timeout=timeout,
                stdout_prefix="[copilot] ",
            )
        else:
            proc = subprocess.run(
                cmd, cwd=cwd, env=merged_env, capture_output=True, text=True, timeout=timeout
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr

        if log_dir is not None:
            (log_dir / "copilot-stdout.log").write_text(stdout or "")
            (log_dir / "copilot-stderr.log").write_text(stderr or "")
            (log_dir / "exit-code.txt").write_text(str(returncode))

        if check and returncode != 0:
            raise CopilotCliError(stderr or f"exit {returncode}")
        return CopilotCliResult(returncode=returncode, stdout=stdout, stderr=stderr)


