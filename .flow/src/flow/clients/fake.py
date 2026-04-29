"""Fake AgentClient for tests (spec §15.1.B)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from flow.clients import AgentResult


@dataclass
class FakeAgentClient:
    """Test double. Optional `on_run` callback writes marker files in `cwd`."""

    name: str = "fake"
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 1
    on_run: Callable[[Path], None] | None = field(default=None)
    calls: list[dict] = field(default_factory=list)

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
        self.calls.append(
            {"prompt": prompt, "cwd": str(cwd), "env": dict(env or {}), "timeout": timeout}
        )
        if self.on_run is not None:
            self.on_run(cwd)
        return AgentResult(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            duration_ms=self.duration_ms,
        )
