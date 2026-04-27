from typing import Literal

State = Literal["agent-ready", "agent-working", "needs-human", "agent-done", "agent-failed"]

STATES: set[str] = {"agent-ready", "agent-working", "needs-human", "agent-done", "agent-failed"}

_TERMINAL: set[str] = {"agent-done", "agent-failed"}

# Map (current_state_or_None, event) -> next_state
_TRANSITIONS: dict[tuple[str | None, str], str] = {
    (None, "label_added:agent-ready"): "agent-ready",
    ("agent-ready", "action_started"): "agent-working",
    ("agent-working", "agent_blocked"): "needs-human",
    ("needs-human", "command:resume"): "agent-working",
    ("agent-working", "merged"): "agent-done",
    ("agent-working", "unrecoverable_error"): "agent-failed",
    # /agent abort from any non-terminal
    ("agent-ready", "command:abort"): "agent-failed",
    ("agent-working", "command:abort"): "agent-failed",
    ("needs-human", "command:abort"): "agent-failed",
    # /agent escalate from any non-terminal
    ("agent-ready", "command:escalate"): "needs-human",
    ("agent-working", "command:escalate"): "needs-human",
    # /agent retry from any non-terminal — restart current stage (stays in same state)
    ("agent-working", "command:retry"): "agent-working",
}


class TransitionError(RuntimeError):
    pass


def next_state_for_event(current: str | None, event: str) -> str | None:
    """Pure function: compute next state, or None if event is invalid here."""
    return _TRANSITIONS.get((current, event))


class StateMachine:
    def __init__(self, current: str | None):
        self.current = current

    def transition(self, event: str) -> None:
        nxt = next_state_for_event(self.current, event)
        if nxt is None:
            raise TransitionError(f"Invalid event {event!r} from state {self.current!r}")
        self.current = nxt

    def is_terminal(self) -> bool:
        return self.current in _TERMINAL
