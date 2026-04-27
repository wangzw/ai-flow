from unittest.mock import MagicMock

import pytest

from sw.github_client import AGENT_LABEL_PREFIX, NEEDS_HUMAN_LABEL, GitHubClient


def _label(name: str):
    lbl = MagicMock()
    lbl.name = name
    return lbl


@pytest.fixture
def fake_issue():
    issue = MagicMock()
    issue.labels = [_label("agent-ready"), _label("bug"), _label("priority/high")]
    return issue


def test_set_state_label_replaces_state_labels_preserving_others(fake_issue):
    client = GitHubClient(gh=MagicMock())
    client.set_state_label(fake_issue, new_label="agent-working")

    fake_issue.set_labels.assert_called_once()
    final = sorted(fake_issue.set_labels.call_args[0])
    assert "agent-working" in final
    assert "agent-ready" not in final
    assert "bug" in final
    assert "priority/high" in final


def test_set_state_label_with_no_existing_state_label(fake_issue):
    fake_issue.labels = [_label("bug")]
    client = GitHubClient(gh=MagicMock())
    client.set_state_label(fake_issue, new_label="agent-ready")
    fake_issue.set_labels.assert_called_once()
    final = sorted(fake_issue.set_labels.call_args[0])
    assert "agent-ready" in final
    assert "bug" in final


def test_set_state_label_rejects_non_state_label(fake_issue):
    client = GitHubClient(gh=MagicMock())
    with pytest.raises(ValueError, match="must start with"):
        client.set_state_label(fake_issue, new_label="some-other-label")


def test_comment_on_issue_calls_create_comment():
    issue = MagicMock()
    client = GitHubClient(gh=MagicMock())
    client.comment_on_issue(issue, "hello")
    issue.create_comment.assert_called_once_with("hello")


def test_get_repo_delegates_to_gh():
    gh = MagicMock()
    client = GitHubClient(gh=gh)
    client.get_repo("owner/name")
    gh.get_repo.assert_called_once_with("owner/name")


def test_constants():
    assert AGENT_LABEL_PREFIX == "agent-"
    assert NEEDS_HUMAN_LABEL == "needs-human"
