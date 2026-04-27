from unittest.mock import MagicMock

import pytest

from sw.gitlab_client import AGENT_LABEL_PREFIX, GitLabClient


@pytest.fixture
def fake_issue():
    issue = MagicMock()
    issue.labels = ["agent-ready", "bug", "priority/high"]
    return issue


def test_set_state_label_removes_all_agent_prefixed_then_adds_new(fake_issue):
    client = GitLabClient(gl=MagicMock())
    client.set_state_label(fake_issue, new_label="agent-working")

    # The new labels should preserve non-agent-* labels and contain only the new agent-*
    new_labels = sorted(fake_issue.labels)
    assert "agent-ready" not in new_labels
    assert "agent-working" in new_labels
    assert "bug" in new_labels
    assert "priority/high" in new_labels
    fake_issue.save.assert_called_once()


def test_set_state_label_with_no_existing_agent_label(fake_issue):
    fake_issue.labels = ["bug"]
    client = GitLabClient(gl=MagicMock())
    client.set_state_label(fake_issue, new_label="agent-ready")
    assert "agent-ready" in fake_issue.labels
    assert "bug" in fake_issue.labels


def test_set_state_label_rejects_non_agent_prefix(fake_issue):
    client = GitLabClient(gl=MagicMock())
    with pytest.raises(ValueError, match="must start with"):
        client.set_state_label(fake_issue, new_label="some-other-label")


def test_comment_on_issue_calls_notes_create():
    issue = MagicMock()
    client = GitLabClient(gl=MagicMock())
    client.comment_on_issue(issue, "hello")
    issue.notes.create.assert_called_once_with({"body": "hello"})


def test_agent_label_prefix_constant():
    assert AGENT_LABEL_PREFIX == "agent-"
