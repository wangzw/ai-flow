"""Subprocess helpers that tee stdout/stderr to console while capturing.

Two modes:

- `run_streaming`: standard pipes + `stdbuf -oL -eL` (when available). Works
  for processes that read stdin. Keeps stdout/stderr separate.

- `run_streaming_pty`: runs the child inside a pseudo-TTY so the C stdlib
  line-buffers automatically. The only reliable way to get real-time output
  on environments where stdout isn't a TTY (e.g. GitHub Actions runners).
  PTY-aware children (like `copilot`) emit ANSI/CR for terminal control;
  we sanitise the stream before forwarding to the parent's console.

Ported from software-workflow's `sw/_subprocess_streaming.py`.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

# ANSI CSI/OSC escape sequences (covers SGR colour codes, cursor moves,
# clear-line). We strip these from PTY output before forwarding.
_ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))"
)


def _sanitise_terminal_output(text: str) -> str:
    text = _ANSI_ESCAPE_RE.sub("", text)
    # Convert CR-only or CRLF to LF; standalone CR (cursor-to-start) becomes LF.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _wrap_with_stdbuf(cmd: list[str]) -> list[str]:
    """Prepend `stdbuf -oL -eL` if available (forces line buffering)."""
    stdbuf = shutil.which("stdbuf")
    if stdbuf is None:
        return cmd
    return [stdbuf, "-oL", "-eL", *cmd]


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
    """Run a subprocess via pipes; tee stdout/stderr to console + capture.

    Returns (returncode, captured_stdout, captured_stderr). The child may
    still block-buffer when stdbuf isn't installed; for guaranteed real-time
    output use `run_streaming_pty`.
    """
    wrapped = _wrap_with_stdbuf(cmd)
    proc = subprocess.Popen(
        wrapped,
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


def run_streaming_pty(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    stdout_prefix: str = "",
) -> tuple[int, str, str]:
    """Run a subprocess inside a pseudo-TTY; output streams in real-time.

    The child sees a TTY → C stdlib line-buffers automatically. Reading the
    master end gives chunks as they arrive. stdout and stderr are merged in
    PTY mode (returned as `stdout`; `stderr` is empty). No stdin support —
    caller must pass input via CLI args.

    POSIX only.
    """
    import pty

    # Discourage TUI/colour output even though the child sees a TTY.
    pty_env = {**env, "TERM": env.get("TERM", "dumb"), "NO_COLOR": "1"}

    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=pty_env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    os.close(slave_fd)

    captured: list[str] = []
    line_carry = ""
    deadline = time.monotonic() + timeout

    def _emit(raw: str) -> None:
        nonlocal line_carry
        text = _sanitise_terminal_output(raw)
        captured.append(text)
        if not stdout_prefix:
            sys.stdout.write(text)
            sys.stdout.flush()
            return
        combined = line_carry + text
        lines = combined.split("\n")
        line_carry = lines[-1]
        for line in lines[:-1]:
            if line.strip():
                sys.stdout.write(f"{stdout_prefix}{line}\n")
        sys.stdout.flush()

    def _flush_carry() -> None:
        nonlocal line_carry
        if line_carry and line_carry.strip():
            sys.stdout.write(f"{stdout_prefix}{line_carry}\n")
            sys.stdout.flush()
        line_carry = ""

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.kill()
            proc.wait()
            os.close(master_fd)
            raise subprocess.TimeoutExpired(cmd, timeout)
        try:
            r, _, _ = select.select([master_fd], [], [], min(remaining, 0.5))
        except (OSError, ValueError):
            break
        if master_fd in r:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            _emit(chunk.decode("utf-8", errors="replace"))
            continue
        if proc.poll() is not None:
            try:
                while True:
                    chunk = os.read(master_fd, 4096)
                    if not chunk:
                        break
                    _emit(chunk.decode("utf-8", errors="replace"))
            except OSError:
                pass
            break

    _flush_carry()
    os.close(master_fd)
    proc.wait()
    return proc.returncode, "".join(captured), ""
