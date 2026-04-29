"""Failed-env classification + retry scheduler (spec §8.3, §8.4).

Categories: model_5xx, rate_limit, sandbox_oom, tool_error, infra, quota.
Schedules next_attempt; cron sweep dispatches due tasks.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

CATEGORIES = ("model_5xx", "rate_limit", "sandbox_oom", "tool_error", "infra", "quota")

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("model_5xx", re.compile(r"\b(5\d{2}|server error|service unavailable|bad gateway)\b", re.I)),
    ("rate_limit", re.compile(r"\b(rate limit|429|too many requests|quota exceeded)\b", re.I)),
    ("sandbox_oom", re.compile(r"\b(killed|oom|out of memory|memory limit)\b", re.I)),
    ("quota", re.compile(r"\b(billing|insufficient_quota|payment required)\b", re.I)),
    ("infra", re.compile(r"\b(connection refused|timed?out|network|dns)\b", re.I)),
    ("tool_error", re.compile(r"\b(command not found|permission denied|exec format)\b", re.I)),
]


def classify_blocker(stdout: str, stderr: str, returncode: int) -> str:
    """Heuristic classifier; defaults to 'tool_error'."""
    text = f"{stdout or ''}\n{stderr or ''}"
    for category, pat in _PATTERNS:
        if pat.search(text):
            return category
    return "tool_error"


def compute_next_attempt(
    *, category: str, attempt: int, retry_config: dict
) -> tuple[datetime | None, dict]:
    """Compute next_attempt UTC datetime and updated state.

    Returns (None, state) if exhausted (caller should escalate to needs-human).
    """
    cfg = (retry_config or {}).get(category) or {}
    max_attempts = int(cfg.get("max_attempts", 0) or 0)
    if max_attempts <= 0 and category != "rate_limit":
        return None, {"category": category, "attempts": attempt, "exhausted": True}

    if category == "rate_limit":
        # spec §8.3: backoff up to max_total_seconds budget
        delay = min(60 * (2 ** min(attempt, 6)), 1800)
    else:
        backoffs = list(cfg.get("backoff") or [60])
        if attempt >= len(backoffs):
            delay = backoffs[-1]
        else:
            delay = backoffs[attempt]

    if max_attempts and attempt >= max_attempts:
        return None, {"category": category, "attempts": attempt, "exhausted": True}

    next_at = datetime.now(timezone.utc) + timedelta(seconds=int(delay))
    return next_at, {
        "category": category,
        "attempts": attempt + 1,
        "next_attempt": next_at.isoformat(),
        "exhausted": False,
    }


def is_due(failed_env: dict | None) -> bool:
    if not failed_env:
        return False
    ts = failed_env.get("next_attempt")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return False
    return datetime.now(timezone.utc) >= dt
