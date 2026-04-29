"""Manifest + task body YAML schema (spec §4.3, §4.4).

The root goal Issue body has YAML frontmatter with a `manifest` array listing
every task in the goal tree. Each task Issue body has its own YAML frontmatter
with `task_id`, `spec`, `deps`, `agent_state`, `review`, etc.

Body format (both):
    ---
    schema_version: 1
    <yaml fields>
    ---

    <human-readable prose>

The frontmatter is parsed/edited by the framework; the prose is human-only.
"""

import re
from dataclasses import dataclass, field
from io import StringIO
from typing import Any

from ruamel.yaml import YAML

SCHEMA_VERSION = 1

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.indent(mapping=2, sequence=4, offset=2)
    y.preserve_quotes = True
    return y


def split_frontmatter(body: str) -> tuple[dict | None, str]:
    """Split a body into (yaml_dict, prose).

    Returns (None, body) if no frontmatter present or malformed (fail-closed
    callers may treat None as a parse error).
    """
    if not body:
        return None, ""
    m = _FRONTMATTER_RE.match(body)
    if not m:
        return None, body
    yaml = YAML(typ="safe")
    try:
        data = yaml.load(StringIO(m.group(1)))
    except Exception:
        return None, body
    if not isinstance(data, dict):
        return None, body
    return data, m.group(2) or ""


def join_frontmatter(data: dict, prose: str) -> str:
    """Serialize (yaml_dict, prose) back into Issue body format."""
    yaml = _yaml()
    buf = StringIO()
    yaml.dump(data, buf)
    return f"---\n{buf.getvalue()}---\n\n{prose.lstrip()}"


# ---------------------------------------------------------------------------
# Manifest entries (root goal body)
# ---------------------------------------------------------------------------

@dataclass
class ManifestEntry:
    task_id: str
    issue: int
    deps: list[str] = field(default_factory=list)
    state: str = "agent-ready"
    parent_task_id: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"task_id": self.task_id, "issue": self.issue, "deps": list(self.deps),
                   "state": self.state}
        if self.parent_task_id is not None:
            d["parent_task_id"] = self.parent_task_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ManifestEntry":
        return cls(
            task_id=str(d["task_id"]),
            issue=int(d["issue"]),
            deps=list(d.get("deps") or []),
            state=str(d.get("state", "agent-ready")),
            parent_task_id=d.get("parent_task_id"),
        )


@dataclass
class GoalAgentState:
    stage: str = "planning"
    last_planner_run: str | None = None
    planner_iteration: int = 0
    dispatch_lock: dict | None = None  # {run_id, acquired_at}
    failed_env_count: int = 0          # tree-level throttle counter (§8.4)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "last_planner_run": self.last_planner_run,
            "planner_iteration": self.planner_iteration,
            "dispatch_lock": self.dispatch_lock,
            "failed_env_count": self.failed_env_count,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "GoalAgentState":
        d = d or {}
        return cls(
            stage=d.get("stage", "planning"),
            last_planner_run=d.get("last_planner_run"),
            planner_iteration=int(d.get("planner_iteration") or 0),
            dispatch_lock=d.get("dispatch_lock"),
            failed_env_count=int(d.get("failed_env_count") or 0),
        )


@dataclass
class GoalBody:
    """Root goal Issue body (spec §4.3)."""

    schema_version: int = SCHEMA_VERSION
    manifest: list[ManifestEntry] = field(default_factory=list)
    agent_state: GoalAgentState = field(default_factory=GoalAgentState)
    prose: str = ""

    def to_body(self) -> str:
        data = {
            "schema_version": self.schema_version,
            "manifest": [m.to_dict() for m in self.manifest],
            "agent_state": self.agent_state.to_dict(),
        }
        return join_frontmatter(data, self.prose)

    @classmethod
    def parse(cls, body: str) -> "GoalBody":
        """Parse a goal body. Missing frontmatter → empty manifest, body kept as prose."""
        data, prose = split_frontmatter(body)
        if data is None:
            return cls(prose=body or "")
        manifest = [ManifestEntry.from_dict(m) for m in (data.get("manifest") or [])]
        agent_state = GoalAgentState.from_dict(data.get("agent_state"))
        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            manifest=manifest,
            agent_state=agent_state,
            prose=prose,
        )

    # convenience
    def find_by_task_id(self, task_id: str) -> ManifestEntry | None:
        for e in self.manifest:
            if e.task_id == task_id:
                return e
        return None

    def find_by_issue(self, issue: int) -> ManifestEntry | None:
        for e in self.manifest:
            if e.issue == issue:
                return e
        return None


# ---------------------------------------------------------------------------
# Task body (spec §4.4)
# ---------------------------------------------------------------------------

@dataclass
class TaskAgentState:
    stage: str = "implementer"  # implementer | reviewer | blocked | planner
    blocker_type: str | None = None
    blocker_details: dict | None = None
    failed_env: dict | None = None
    progress: str | None = None
    decision_response: str | None = None  # injected by /agent decide

    def to_dict(self) -> dict:
        d: dict = {"stage": self.stage, "blocker_type": self.blocker_type}
        if self.blocker_details is not None:
            d["blocker_details"] = self.blocker_details
        if self.failed_env is not None:
            d["failed_env"] = self.failed_env
        if self.progress is not None:
            d["progress"] = self.progress
        if self.decision_response is not None:
            d["decision_response"] = self.decision_response
        return d

    @classmethod
    def from_dict(cls, d: dict | None) -> "TaskAgentState":
        d = d or {}
        return cls(
            stage=d.get("stage", "implementer"),
            blocker_type=d.get("blocker_type"),
            blocker_details=d.get("blocker_details"),
            failed_env=d.get("failed_env"),
            progress=d.get("progress"),
            decision_response=d.get("decision_response"),
        )


@dataclass
class ReviewState:
    iteration: int = 0
    max_iterations: int = 5
    arbitrations: int = 0
    max_arbitrations: int = 2
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "arbitrations": self.arbitrations,
            "max_arbitrations": self.max_arbitrations,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "ReviewState":
        d = d or {}
        return cls(
            iteration=int(d.get("iteration") or 0),
            max_iterations=int(d.get("max_iterations") or 5),
            arbitrations=int(d.get("arbitrations") or 0),
            max_arbitrations=int(d.get("max_arbitrations") or 2),
            history=list(d.get("history") or []),
        )


@dataclass
class TaskSpec:
    goal: str = ""
    constraints: dict = field(default_factory=dict)
    quality_criteria: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "constraints": dict(self.constraints),
            "quality_criteria": list(self.quality_criteria),
            "steps": list(self.steps),
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "TaskSpec":
        d = d or {}
        return cls(
            goal=str(d.get("goal", "")),
            constraints=dict(d.get("constraints") or {}),
            quality_criteria=list(d.get("quality_criteria") or []),
            steps=list(d.get("steps") or []),
        )


def render_task_prose(*, task_id: str, goal_issue: int, spec: TaskSpec,
                      deps: list[str] | None = None) -> str:
    """Render a short human-readable summary of a task spec.

    Goes after the YAML frontmatter so humans browsing the issue see the
    purpose, acceptance criteria and steps without parsing YAML.
    """
    lines: list[str] = []
    lines.append(f"## Task `{task_id}`")
    lines.append("")
    if goal_issue:
        lines.append(f"Parent goal: #{goal_issue}")
        lines.append("")
    if spec.goal:
        lines.append("### Goal")
        lines.append(spec.goal.strip())
        lines.append("")
    qc = [str(c).strip() for c in (spec.quality_criteria or []) if str(c).strip()]
    if qc:
        lines.append("### Acceptance criteria")
        for c in qc:
            lines.append(f"- {c}")
        lines.append("")
    steps = spec.steps or []
    if steps:
        lines.append("### Steps")
        for i, s in enumerate(steps, 1):
            desc = ""
            if isinstance(s, dict):
                desc = str(s.get("description") or s.get("id") or "").strip()
            else:
                desc = str(s).strip()
            if desc:
                lines.append(f"{i}. {desc}")
        lines.append("")
    if deps:
        lines.append("### Depends on")
        lines.append(", ".join(f"`{d}`" for d in deps))
        lines.append("")
    lines.append("> _The YAML block above is machine-managed by ai-flow; "
                 "do not edit it by hand._")
    return "\n".join(lines).rstrip() + "\n"


@dataclass
class TaskBody:
    """Task Issue body (spec §4.4)."""

    schema_version: int = SCHEMA_VERSION
    task_id: str = ""
    goal_issue: int = 0
    parent_task_id: str | None = None
    spec: TaskSpec = field(default_factory=TaskSpec)
    deps: list[str] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    review: ReviewState = field(default_factory=ReviewState)
    agent_state: TaskAgentState = field(default_factory=TaskAgentState)
    prose: str = ""

    def to_body(self) -> str:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "goal_issue": self.goal_issue,
            "parent_task_id": self.parent_task_id,
            "spec": self.spec.to_dict(),
            "deps": list(self.deps),
            "artifacts": list(self.artifacts),
            "review": self.review.to_dict(),
            "agent_state": self.agent_state.to_dict(),
        }
        return join_frontmatter(data, self.prose)

    @classmethod
    def parse(cls, body: str) -> "TaskBody":
        data, prose = split_frontmatter(body)
        if data is None:
            return cls(prose=body or "")
        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            task_id=str(data.get("task_id", "") or ""),
            goal_issue=int(data.get("goal_issue") or 0),
            parent_task_id=data.get("parent_task_id"),
            spec=TaskSpec.from_dict(data.get("spec")),
            deps=list(data.get("deps") or []),
            artifacts=list(data.get("artifacts") or []),
            review=ReviewState.from_dict(data.get("review")),
            agent_state=TaskAgentState.from_dict(data.get("agent_state")),
            prose=prose,
        )
