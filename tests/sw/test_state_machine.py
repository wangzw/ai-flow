import pytest

from sw.state_machine import (
    STATES,
    StateMachine,
    TransitionError,
    next_state_for_event,
)


def test_states_match_spec():
    expected = {"agent-ready", "agent-working", "needs-human", "agent-done", "agent-failed"}
    assert STATES == expected


def test_initial_label_to_ready():
    sm = StateMachine(current=None)
    sm.transition(event="label_added:agent-ready")
    assert sm.current == "agent-ready"


def test_ready_to_working_on_action_start():
    sm = StateMachine(current="agent-ready")
    sm.transition(event="action_started")
    assert sm.current == "agent-working"


def test_working_to_needs_human_on_block():
    sm = StateMachine(current="agent-working")
    sm.transition(event="agent_blocked")
    assert sm.current == "needs-human"


def test_needs_human_to_working_on_resume():
    sm = StateMachine(current="needs-human")
    sm.transition(event="command:resume")
    assert sm.current == "agent-working"


def test_working_to_done_on_merge():
    sm = StateMachine(current="agent-working")
    sm.transition(event="merged")
    assert sm.current == "agent-done"


def test_working_to_failed_on_unrecoverable():
    sm = StateMachine(current="agent-working")
    sm.transition(event="unrecoverable_error")
    assert sm.current == "agent-failed"


def test_command_abort_from_any_non_terminal():
    for state in ["agent-ready", "agent-working", "needs-human"]:
        sm = StateMachine(current=state)
        sm.transition(event="command:abort")
        assert sm.current == "agent-failed"


def test_command_escalate_from_any_non_terminal():
    for state in ["agent-ready", "agent-working"]:
        sm = StateMachine(current=state)
        sm.transition(event="command:escalate")
        assert sm.current == "needs-human"


def test_invalid_transition_raises():
    sm = StateMachine(current="agent-done")
    with pytest.raises(TransitionError):
        sm.transition(event="agent_blocked")


def test_resume_from_working_is_invalid():
    sm = StateMachine(current="agent-working")
    with pytest.raises(TransitionError):
        sm.transition(event="command:resume")


def test_next_state_for_event_pure_function():
    # Exposed for callers who don't want to instantiate StateMachine
    assert next_state_for_event("agent-working", "merged") == "agent-done"
    assert next_state_for_event("needs-human", "command:resume") == "agent-working"
    assert next_state_for_event("agent-done", "agent_blocked") is None


def test_is_terminal_recognizes_done_and_failed():
    assert StateMachine(current="agent-done").is_terminal() is True
    assert StateMachine(current="agent-failed").is_terminal() is True
    assert StateMachine(current="agent-working").is_terminal() is False
    assert StateMachine(current="needs-human").is_terminal() is False
