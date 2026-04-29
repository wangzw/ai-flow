"""Subprocess wrapper for `copilot` CLI (spec §2.4).

Streams the child's stdout/stderr to the parent's console in real time so
operators can watch progress in the GitHub Actions log live, while still
capturing the full output for post-run logs and metrics.
"""

import os
import subprocess
import time
from pathlib import Path

from flow.clients import AgentResult
from flow.clients._streaming import run_streaming, run_streaming_pty


class CopilotCliError(RuntimeError):
    """Raised when copilot subprocess exits non-zero with check=True."""


class CopilotCliClient:
    name = "copilot"

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
        stream: bool = True,
        use_pty: bool | None = None,
    ) -> AgentResult:
        """Invoke `copilot` non-interactively with --prompt and --allow-all.

        - `stream=True` (default): tee stdout/stderr to the parent console as
          the child runs. Uses PTY mode on POSIX (so the child line-buffers
          automatically — required for live output on Actions runners), or
          pipe+stdbuf mode otherwise.
        - `stream=False`: capture-only fallback (used by tests that patch
          `subprocess.run`).
        - `use_pty=None` (default): auto-detect (POSIX → True, else False).
        """
        cmd = [self.executable, "--prompt", prompt, "--allow-all"]
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--log-dir", str(log_dir), "--log-level", "debug"])

        merged_env = {**os.environ, **(env or {})}

        t0 = time.monotonic()
        if stream:
            pty_mode = use_pty if use_pty is not None else (os.name == "posix")
            if pty_mode:
                returncode, stdout, stderr = run_streaming_pty(
                    cmd,
                    cwd=cwd,
                    env=merged_env,
                    timeout=timeout,
                    stdout_prefix="[copilot] ",
                )
            else:
                returncode, stdout, stderr = run_streaming(
                    cmd,
                    cwd=cwd,
                    env=merged_env,
                    timeout=timeout,
                    stdout_prefix="[copilot] ",
                    stderr_prefix="[copilot:err] ",
                )
        else:
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if log_dir is not None:
            # Re-create in case the subprocess wiped the dir (e.g., LLM ran
            # `git clean -fdx` or similar inside cwd).
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "copilot-stdout.log").write_text(stdout or "")
            (log_dir / "copilot-stderr.log").write_text(stderr or "")
            (log_dir / "exit-code.txt").write_text(str(returncode))

        if check and returncode != 0:
            raise CopilotCliError(stderr or f"exit {returncode}")

        return AgentResult(
            returncode=returncode,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=elapsed_ms,
        )


# Re-exported for callers that want to know whether they're being streamed.
__all__ = ["CopilotCliClient", "CopilotCliError"]

