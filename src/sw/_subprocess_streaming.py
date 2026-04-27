"""Subprocess helper that tees stdout/stderr to console while capturing.

Two modes:

- `run_streaming`: standard pipes + stdbuf wrapping. Works for processes that
  read stdin. stdout and stderr stay separate. May still block-buffer if the
  child detects pipes and stdbuf isn't installed.

- `run_streaming_pty`: allocates a pseudo-TTY for the child. The child sees a
  TTY on its stdout/stderr and switches to LINE buffering automatically. This
  is the only reliable way to get real-time output on environments without
  a controlling terminal (e.g. GitHub Actions runners). stdin is NOT supported
  in PTY mode (caller must pass the prompt as a CLI arg).

  PTY-aware children (like copilot) emit ANSI escape sequences and `\\r` for
  terminal control. We sanitise the output stream before forwarding to the
  parent's console: strip escape sequences and convert CRLF to LF.

Used by `claude_code_client` (run_streaming with stdin) and `copilot_cli_client`
(run_streaming_pty for real-time visibility on Actions runners).
"""

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

# ANSI CSI/OSC escape sequences (covers SGR colour codes, cursor moves, clear-line).
_ANSI_ESCAPE_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\))"
)


def _sanitise_terminal_output(text: str) -> str:
    """Strip ANSI escape sequences and normalise carriage returns to LF."""
    text = _ANSI_ESCAPE_RE.sub("", text)
    # Convert CR-only or CRLF to LF; standalone CR (cursor-to-start) becomes LF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _wrap_with_stdbuf(cmd: list[str]) -> list[str]:
    """Prepend `stdbuf -oL -eL` if available (forces child to line-buffer)."""
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
    """Run a subprocess via pipes; tee stdout/stderr to console + capture both.

    Returns (returncode, captured_stdout, captured_stderr).

    Note: child may still block-buffer when stdbuf isn't installed. For
    guaranteed real-time output prefer `run_streaming_pty` (no stdin).
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

    The child sees a TTY on its stdout/stderr → C stdlib line-buffers automatically.
    Reading the master end gives chunks as they arrive. We prefix each line and
    forward to sys.stdout. stdout and stderr are merged in PTY mode (returned
    as captured_stdout; captured_stderr is empty).

    No stdin support — caller must supply input via CLI args.

    Available on POSIX only (Linux/macOS). Windows callers should fall back
    to `run_streaming`.
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
        # Strip ANSI/CR before both capture AND console write.
        text = _sanitise_terminal_output(raw)
        captured.append(text)
        if not stdout_prefix:
            sys.stdout.write(text)
            sys.stdout.flush()
            return
        # Prefix each complete line; carry partial last line to next chunk.
        combined = line_carry + text
        lines = combined.split("\n")
        line_carry = lines[-1]
        for line in lines[:-1]:
            if line.strip():  # skip blank lines from CR -> LF conversion
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
            # drain pending bytes then exit
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
