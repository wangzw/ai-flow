"""Project-level config loader (.flow/config.yml, spec §13.4)."""

from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

DEFAULT_CONFIG_PATH = Path(".flow/config.yml")


@dataclass
class Config:
    version: int = 1
    platform: str = "github"
    models: dict = field(default_factory=lambda: {
        "planner_cli": "copilot",
        "implementer_cli": "copilot",
        "reviewer_cli": "copilot",
    })
    review: dict = field(default_factory=lambda: {
        "max_iterations": 5,
        "max_arbitrations": 2,
        "dimensions": {
            "must": ["spec_compliance", "test_quality", "security",
                     "consistency", "migration_safety"],
            "may": ["performance", "documentation_sync"],
        },
    })
    blast_radius: dict = field(default_factory=lambda: {
        "core_modules": [],
        "migration_globs": ["migrations/", "*.sql"],
    })
    retry: dict = field(default_factory=lambda: {
        "model_5xx":   {"max_attempts": 5, "backoff": [30, 60, 120, 240, 480]},
        "rate_limit":  {"max_total_seconds": 3600},
        "sandbox_oom": {"max_attempts": 2},
        "tool_error":  {"max_attempts": 3, "backoff": [60, 120, 240]},
        "infra":       {"max_attempts": 5, "backoff": [30, 60, 120, 240, 480]},
        "quota":       {"max_attempts": 0},
    })
    throttle: dict = field(default_factory=lambda: {
        "max_parallel_tasks": 5,
        "goal_failure_threshold": 10,
    })
    authorized_users: list[str] = field(default_factory=list)
    channel_discipline: dict = field(default_factory=lambda: {
        "reviewer_input_excludes": ["commit_message", "pr_description", "implementer_summary"],
    })
    cost: dict = field(default_factory=lambda: {
        "enable_tracking": True,
        "estimate_tokens_when_unavailable": True,
        "per_second_rate_usd": 0.0015,
    })

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        """Load config from YAML; returns defaults if file missing."""
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        if not p.exists():
            return cls()
        yaml = YAML(typ="safe")
        data = yaml.load(StringIO(p.read_text(encoding="utf-8"))) or {}
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    def is_authorized(self, login: str | None) -> bool:
        if not login:
            return False
        return login in self.authorized_users
