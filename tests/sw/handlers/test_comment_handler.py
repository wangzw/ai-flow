from unittest.mock import MagicMock

from sw.handlers.comment_handler import handle_comment_event


def _make_issue(labels):
    issue = MagicMock()
    issue.labels = list(labels)
    issue.iid = 42
    return issue


def test_resume_from_needs_human_transitions_to_working():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["needs-human"])
    client = MagicMock()
    coder = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="ok do option keep\n/agent resume",
        client=client,
        coder=coder,
    )

    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-working" in labels
    coder.assert_called_once()


def test_abort_transitions_to_failed():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="/agent abort",
        client=client,
        coder=MagicMock(),
    )

    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-failed" in labels


def test_escalate_transitions_to_needs_human():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="/agent escalate",
        client=client,
        coder=MagicMock(),
    )

    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "needs-human" in labels


def test_resume_from_invalid_state_is_no_op():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()
    coder = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="/agent resume",
        client=client,
        coder=coder,
    )

    client.set_state_label.assert_not_called()
    coder.assert_not_called()


def test_no_command_is_no_op():
    project = MagicMock()
    project.issues.get.return_value = _make_issue(["agent-working"])
    client = MagicMock()

    handle_comment_event(
        project=project,
        issue_iid=42,
        comment_body="just chatting",
        client=client,
        coder=MagicMock(),
    )

    client.set_state_label.assert_not_called()
