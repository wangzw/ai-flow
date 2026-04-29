"""Agent client Protocol (spec §2.4)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AgentResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int = 0


class AgentClient(Protocol):
    name: str  # "copilot" or "claude" — for cost reporting

    def run(
        self,
        *,
        prompt: str,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int = 1800,
        check: bool = False,
        log_dir: Path | None = None,
    ) -> AgentResult: ...
