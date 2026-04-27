from unittest.mock import MagicMock

from sw.handlers.issue_handler import handle_issue_event


def _make_issue(*, body: str, labels: list[str], iid: int = 42, title: str = "t"):
    issue = MagicMock()
    issue.description = body
    issue.labels = list(labels)
    issue.iid = iid
    issue.title = title
    return issue


VALID_BODY = """## AC
<!-- ac:start -->
something testable
<!-- ac:end -->
"""


def test_label_added_agent_ready_with_valid_ac_runs_coder():
    project = MagicMock()
    issue = _make_issue(body=VALID_BODY, labels=["agent-ready"])
    project.issues.get.return_value = issue

    coder = MagicMock(return_value=MagicMock(success=True, mr_iid=99))
    client = MagicMock()

    handle_issue_event(
        project=project,
        issue_iid=42,
        action="label_added",
        label="agent-ready",
        client=client,
        coder=coder,
    )

    # transitioned ready -> working before invoking coder
    set_calls = client.set_state_label.call_args_list
    labels_set = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-working" in labels_set
    coder.assert_called_once()


def test_label_added_agent_ready_with_missing_ac_transitions_to_needs_human():
    project = MagicMock()
    issue = _make_issue(body="no AC here", labels=["agent-ready"])
    project.issues.get.return_value = issue

    coder = MagicMock()
    client = MagicMock()

    handle_issue_event(
        project=project,
        issue_iid=42,
        action="label_added",
        label="agent-ready",
        client=client,
        coder=coder,
    )

    set_calls = client.set_state_label.call_args_list
    labels_set = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "needs-human" in labels_set
    coder.assert_not_called()
    client.comment_on_issue.assert_called_once()
    body = client.comment_on_issue.call_args[0][1]
    assert "ac" in body.lower()


def test_other_label_does_nothing():
    project = MagicMock()
    issue = _make_issue(body=VALID_BODY, labels=["bug"])
    project.issues.get.return_value = issue

    coder = MagicMock()
    client = MagicMock()

    handle_issue_event(
        project=project,
        issue_iid=42,
        action="label_added",
        label="bug",
        client=client,
        coder=coder,
    )

    client.set_state_label.assert_not_called()
    coder.assert_not_called()


def test_coder_returns_blocker_transitions_to_needs_human():
    project = MagicMock()
    issue = _make_issue(body=VALID_BODY, labels=["agent-ready"])
    project.issues.get.return_value = issue

    blocker = {
        "blocker_type": "ac_ambiguity",
        "question": "How?",
        "options": [{"id": "a", "desc": "A"}],
    }
    coder = MagicMock(
        return_value=MagicMock(success=False, mr_iid=None, blocker=blocker)
    )
    client = MagicMock()

    handle_issue_event(
        project=project,
        issue_iid=42,
        action="label_added",
        label="agent-ready",
        client=client,
        coder=coder,
    )

    set_calls = client.set_state_label.call_args_list
    labels_set = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert labels_set == ["agent-working", "needs-human"]
    client.comment_on_issue.assert_called_once()
    body = client.comment_on_issue.call_args[0][1]
    assert "How?" in body
