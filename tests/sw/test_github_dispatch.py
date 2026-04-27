"""Smoke tests for github_dispatch CLI parsing.

The command bodies are platform-specific and tested at integration level.
Here we just verify the entry point routes commands correctly.
"""

from unittest.mock import MagicMock, patch

from sw import github_dispatch


def test_unknown_command_exits_2(capsys):
    rc = github_dispatch.main(["bogus"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "usage" in captured.err.lower()


def test_no_command_exits_2(capsys):
    rc = github_dispatch.main([])
    assert rc == 2


def test_known_commands_routed(monkeypatch):
    """Each declared command resolves to a callable."""
    expected = {"issue-labeled", "comment-created", "pr-ready", "merge-queue"}
    assert set(github_dispatch._COMMANDS.keys()) == expected
    for name, fn in github_dispatch._COMMANDS.items():
        assert callable(fn), f"{name} not callable"


def test_issue_labeled_invokes_coder_gh_on_valid_ac(monkeypatch):
    """When AC valid, coder_gh.run_coder_gh is called."""
    monkeypatch.setenv("GITHUB_TOKEN", "tk")
    monkeypatch.setenv("SW_REPO", "owner/name")
    monkeypatch.setenv("SW_ISSUE_NUMBER", "42")
    monkeypatch.setenv("SW_LABEL_ADDED", "agent-ready")

    fake_client = MagicMock()
    fake_repo = MagicMock()
    fake_issue = MagicMock()
    fake_issue.number = 42
    fake_issue.title = "t"
    fake_issue.body = "## AC\n<!-- ac:start -->\nDo X\n<!-- ac:end -->"
    fake_repo.get_issue.return_value = fake_issue
    fake_client.get_repo.return_value = fake_repo

    with patch("sw.github_dispatch._client", return_value=fake_client), \
         patch("sw.github_dispatch.run_coder_gh") as mock_coder:
        mock_coder.return_value = MagicMock(success=True, blocker=None)
        rc = github_dispatch.cmd_issue_labeled()

    assert rc == 0
    mock_coder.assert_called_once()
    set_calls = fake_client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-working" in labels


def test_issue_labeled_posts_needs_human_on_invalid_ac(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tk")
    monkeypatch.setenv("SW_REPO", "owner/name")
    monkeypatch.setenv("SW_ISSUE_NUMBER", "42")
    monkeypatch.setenv("SW_LABEL_ADDED", "agent-ready")

    fake_client = MagicMock()
    fake_repo = MagicMock()
    fake_issue = MagicMock()
    fake_issue.number = 42
    fake_issue.body = "no AC here"
    fake_repo.get_issue.return_value = fake_issue
    fake_client.get_repo.return_value = fake_repo

    with patch("sw.github_dispatch._client", return_value=fake_client):
        rc = github_dispatch.cmd_issue_labeled()

    assert rc == 0
    fake_client.comment_on_issue.assert_called_once()
    set_calls = fake_client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "needs-human" in labels


def test_issue_labeled_skips_non_agent_ready(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tk")
    monkeypatch.setenv("SW_REPO", "owner/name")
    monkeypatch.setenv("SW_ISSUE_NUMBER", "42")
    monkeypatch.setenv("SW_LABEL_ADDED", "bug")

    with patch("sw.github_dispatch._client") as mock_client:
        rc = github_dispatch.cmd_issue_labeled()
    assert rc == 0
    mock_client.assert_not_called()


def test_merge_queue_invokes_processor(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tk")
    monkeypatch.setenv("SW_REPO", "owner/name")

    fake_client = MagicMock()
    fake_repo = MagicMock()
    fake_client.get_repo.return_value = fake_repo

    with patch("sw.github_dispatch._client", return_value=fake_client), \
         patch("sw.github_dispatch.process_merge_queue_gh") as mock_proc:
        mock_proc.return_value = 0
        rc = github_dispatch.cmd_merge_queue()
    assert rc == 0
    mock_proc.assert_called_once()
