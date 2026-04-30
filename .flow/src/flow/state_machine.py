"""ai-flow external state machine (spec §3).

5-state model: every Issue (goal or task) carries exactly one state label.
Internal blocker subtypes (review iteration, failed_env category) live in
Issue body YAML `agent_state` — never in labels (spec §3.1).
"""

from typing import Literal

State = Literal["agent-ready", "agent-working", "needs-human", "agent-done", "agent-failed"]

STATES: set[str] = {
    "agent-ready",
    "agent-working",
    "needs-human",
    "agent-done",
    "agent-failed",
}

EXTERNAL_STATES = STATES  # alias used by reconciler
TERMINAL_STATES: set[str] = {"agent-done", "agent-failed"}

# Map (current_state_or_None, event) -> next_state. Spec §3.4.
_TRANSITIONS: dict[tuple[str | None, str], str] = {
    (None, "label_added:agent-ready"): "agent-ready",
    (None, "command:start"): "agent-ready",
    ("agent-ready", "action_started"): "agent-working",
    # Planner internal reconcile loop is allowed self-edge.
    ("agent-working", "planner_reconciled"): "agent-working",
    ("agent-working", "agent_blocked"): "needs-human",
    ("agent-working", "merged"): "agent-done",
    ("agent-working", "planner_done"): "agent-done",
    ("agent-working", "unrecoverable_error"): "agent-failed",
    ("needs-human", "command:resume"): "agent-working",
    ("needs-human", "command:decide"): "agent-working",
    ("needs-human", "command:replan"): "agent-working",
    # /agent abort from any non-terminal
    ("agent-ready", "command:abort"): "agent-failed",
    ("agent-working", "command:abort"): "agent-failed",
    ("needs-human", "command:abort"): "agent-failed",
    # /agent escalate from any non-terminal
    ("agent-ready", "command:escalate"): "needs-human",
    ("agent-working", "command:escalate"): "needs-human",
    # /agent retry — restart current stage; stays in same state
    ("agent-working", "command:retry"): "agent-working",
    ("agent-ready", "command:retry"): "agent-ready",
    # /agent replan re-runs Planner. Allowed from any non-terminal state on
    # the goal — the Planner is reactive and re-derives the plan from current
    # child state every invocation, so it is always safe to ask for a fresh
    # plan even while children are mid-flight.
    ("agent-ready", "command:replan"): "agent-working",
    ("agent-working", "command:replan"): "agent-working",
}


class TransitionError(RuntimeError):
    """Invalid (state, event) pair per spec §3.4."""


def next_state_for_event(current: str | None, event: str) -> str | None:
    """Pure function: compute next state, or None if event is invalid."""
    return _TRANSITIONS.get((current, event))


def is_terminal(state: str | None) -> bool:
    return state in TERMINAL_STATES


class StateMachine:
    def __init__(self, current: str | None):
        self.current = current

    def transition(self, event: str) -> None:
        nxt = next_state_for_event(self.current, event)
        if nxt is None:
            raise TransitionError(f"Invalid event {event!r} from state {self.current!r}")
        self.current = nxt

    def is_terminal(self) -> bool:
        return is_terminal(self.current)
