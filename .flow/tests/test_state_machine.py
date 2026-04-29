from flow.state_machine import (
    STATES,
    TERMINAL_STATES,
    StateMachine,
    TransitionError,
    is_terminal,
    next_state_for_event,
)


def test_states_and_terminal():
    assert STATES == {"agent-ready", "agent-working", "needs-human",
                      "agent-done", "agent-failed"}
    assert TERMINAL_STATES == {"agent-done", "agent-failed"}


def test_label_added_creates_ready():
    assert next_state_for_event(None, "label_added:agent-ready") == "agent-ready"


def test_action_started():
    assert next_state_for_event("agent-ready", "action_started") == "agent-working"


def test_blocker_to_human():
    assert next_state_for_event("agent-working", "agent_blocked") == "needs-human"


def test_resume_from_human():
    assert next_state_for_event("needs-human", "command:resume") == "agent-working"
    assert next_state_for_event("needs-human", "command:decide") == "agent-working"
    assert next_state_for_event("needs-human", "command:replan") == "agent-working"


def test_planner_done_terminal():
    assert next_state_for_event("agent-working", "planner_done") == "agent-done"
    assert next_state_for_event("agent-working", "merged") == "agent-done"


def test_abort_from_anywhere():
    for s in ("agent-ready", "agent-working", "needs-human"):
        assert next_state_for_event(s, "command:abort") == "agent-failed"


def test_invalid_transition_returns_none():
    assert next_state_for_event("agent-done", "command:resume") is None


def test_state_machine_class():
    sm = StateMachine(current=None)
    sm.transition("label_added:agent-ready")
    assert sm.current == "agent-ready"
    sm.transition("action_started")
    assert sm.current == "agent-working"
    sm.transition("agent_blocked")
    assert sm.current == "needs-human"
    assert not sm.is_terminal()
    sm.transition("command:abort")
    assert sm.current == "agent-failed"
    assert sm.is_terminal()


def test_invalid_raises():
    sm = StateMachine(current="agent-done")
    try:
        sm.transition("command:resume")
    except TransitionError:
        pass
    else:
        raise AssertionError("expected TransitionError")


def test_is_terminal():
    assert is_terminal("agent-done")
    assert is_terminal("agent-failed")
    assert not is_terminal("agent-working")
    assert not is_terminal(None)
