"""Subprocess helper that tees stdout/stderr to console while capturing.

Used by `claude_code_client` and `copilot_cli_client` to give real-time
visibility into long-running CLI agentic sessions in CI logs while still
returning the full output for downstream parsing.
"""

import subprocess
import sys
import threading
from pathlib import Path
from typing import IO


def run_streaming(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    input_data: str | None = None,
    stdout_prefix: str = "",
    stderr_prefix: str = "",
) -> tuple[int, str, str]:
    """Run a subprocess; tee stdout/stderr to parent console + capture both.

    Returns (returncode, captured_stdout, captured_stderr).
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_data is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_buf: list[str] = []
    stderr_buf: list[str] = []

    def _tee(pipe: IO[str], buf: list[str], prefix: str, out: IO[str]):
        for line in pipe:
            buf.append(line)
            out.write(f"{prefix}{line}" if prefix else line)
            out.flush()

    t_out = threading.Thread(
        target=_tee, args=(proc.stdout, stdout_buf, stdout_prefix, sys.stdout)
    )
    t_err = threading.Thread(
        target=_tee, args=(proc.stderr, stderr_buf, stderr_prefix, sys.stderr)
    )
    t_out.start()
    t_err.start()

    if input_data is not None and proc.stdin is not None:
        try:
            proc.stdin.write(input_data)
            proc.stdin.close()
        except BrokenPipeError:
            pass

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        t_out.join()
        t_err.join()
        raise

    t_out.join()
    t_err.join()
    return proc.returncode, "".join(stdout_buf), "".join(stderr_buf)
