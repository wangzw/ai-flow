"""Cron sweep: failed-env retries + planner re-entry queue (spec §8.4)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from flow.clients.github import GitHubClient
from flow.human_messages import schedule_retry_dispatch_comment
from flow.manifest import TaskBody
from flow.retry import is_due


def handle_schedule() -> int:
    gh = GitHubClient.from_env()
    repo = gh.get_repo(os.environ["FLOW_REPO"])

    # Sweep agent-ready tasks whose failed_env.next_attempt has passed but
    # weren't dispatched (rare — most tasks dispatch on label add). We just
    # nudge them by re-applying the label.
    for issue in repo.get_issues(state="open", labels=["agent-ready", "type:task"]):
        body = TaskBody.parse(issue.body or "")
        fenv = body.agent_state.failed_env
        if fenv and is_due(fenv):
            print(f"[sched] re-dispatching task #{issue.number} (failed_env={fenv})",
                  flush=True)
            issue.create_comment(
                schedule_retry_dispatch_comment(
                    now_iso=datetime.now(timezone.utc).isoformat(),
                )
            )
            # Toggle label to retrigger
            issue.remove_from_labels("agent-ready")
            issue.add_to_labels("agent-ready")
    return 0
