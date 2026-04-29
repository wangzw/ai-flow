"""Tests for the subprocess streaming helper.

We exercise both run_streaming and (on POSIX) run_streaming_pty using a
short Python subprocess so the test is fast and self-contained.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from flow.clients._streaming import run_streaming, run_streaming_pty


def test_run_streaming_captures_stdout_and_stderr(tmp_path: Path, capsys):
    rc, out, err = run_streaming(
        [sys.executable, "-u", "-c",
         "import sys; print('hello-out'); print('hello-err', file=sys.stderr)"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=10,
    )
    assert rc == 0
    assert "hello-out" in out
    assert "hello-err" in err
    # Tee'd to console too
    captured = capsys.readouterr()
    assert "hello-out" in captured.out
    assert "hello-err" in captured.err


@pytest.mark.skipif(os.name != "posix", reason="PTY is POSIX-only")
def test_run_streaming_pty_captures_merged_output(tmp_path: Path, capsys):
    rc, out, err = run_streaming_pty(
        [sys.executable, "-u", "-c",
         "import sys; print('pty-out'); print('pty-err', file=sys.stderr)"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=10,
        stdout_prefix="[t] ",
    )
    assert rc == 0
    assert err == ""  # PTY merges stderr into stdout
    # Both lines arrived in the captured stream
    assert "pty-out" in out
    assert "pty-err" in out
    # Forwarded to the parent's stdout with our prefix
    captured = capsys.readouterr()
    assert "[t] pty-out" in captured.out
