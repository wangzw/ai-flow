"""Subprocess wrapper for `copilot` CLI (spec §2.4)."""

import os
import subprocess
import time
from pathlib import Path

from flow.clients import AgentResult


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
    ) -> AgentResult:
        cmd = [self.executable, "--prompt", prompt, "--allow-all"]
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            cmd.extend(["--log-dir", str(log_dir), "--log-level", "debug"])

        merged_env = {**os.environ, **(env or {})}
        t0 = time.monotonic()
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if log_dir is not None:
            (log_dir / "copilot-stdout.log").write_text(proc.stdout or "")
            (log_dir / "copilot-stderr.log").write_text(proc.stderr or "")
            (log_dir / "exit-code.txt").write_text(str(proc.returncode))

        if check and proc.returncode != 0:
            raise CopilotCliError(proc.stderr or f"exit {proc.returncode}")

        return AgentResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_ms=elapsed_ms,
        )
