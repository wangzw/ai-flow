"""When a /agent command is accepted, ack via 👍 reaction on the user's
comment instead of posting a reply comment. Falls back to comment if the
reaction call fails or the comment id wasn't passed by the workflow."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class _FakeLabel:
    def __init__(self, name: str):
        self.name = name


class _FakeIssue:
    def __init__(self, number: int = 7, labels=None, body: str = ""):
        self.number = number
        self.labels = [_FakeLabel(n) for n in (labels or ["agent-failed"])]
        self.body = body
        self.create_comment = MagicMock()
        self.get_comment = MagicMock()


def _setup_env(monkeypatch, *, comment_id: str | None):
    monkeypatch.setenv("FLOW_REPO", "owner/repo")
    monkeypatch.setenv("FLOW_ISSUE_NUMBER", "7")
    monkeypatch.setenv("FLOW_COMMENT_BODY", "/agent abort")
    monkeypatch.setenv("FLOW_COMMENT_AUTHOR", "alice")
    if comment_id is not None:
        monkeypatch.setenv("FLOW_COMMENT_ID", comment_id)
    else:
        monkeypatch.delenv("FLOW_COMMENT_ID", raising=False)


def _patch_handler(monkeypatch, issue, *, react_succeeds: bool):
    """Patch GitHubClient + Config + is_authorized; return (gh_mock, ack_calls)."""
    import flow.handlers.comment_handler as mod

    gh = MagicMock()
    gh.get_repo.return_value.get_issue.return_value = issue
    gh.react_to_comment.return_value = react_succeeds

    monkeypatch.setattr(mod.GitHubClient, "from_env", classmethod(lambda cls: gh))
    monkeypatch.setattr(mod, "is_authorized", lambda *a, **kw: True)

    fake_cfg = MagicMock()
    fake_cfg.authorized_users = ["alice"]
    monkeypatch.setattr(mod.Config, "load", classmethod(lambda cls: fake_cfg))

    return gh


def test_accepted_command_uses_thumbsup_reaction(monkeypatch):
    """Happy path: comment id provided, reaction succeeds → no reply comment."""
    _setup_env(monkeypatch, comment_id="12345")
    issue = _FakeIssue(labels=["needs-human"])
    from flow.handlers import comment_handler as mod

    gh = _patch_handler(monkeypatch, issue, react_succeeds=True)
    rc = mod.handle_comment_created()

    assert rc == 0
    gh.react_to_comment.assert_called_once()
    args, kwargs = gh.react_to_comment.call_args
    assert kwargs.get("reaction") == "+1" or "+1" in args
    # No fallback ack comment posted
    ack_comment_calls = [c for c in gh.comment.call_args_list]
    assert ack_comment_calls == [], f"unexpected ack comment: {ack_comment_calls}"


def test_reaction_failure_falls_back_to_comment(monkeypatch):
    """If react fails, post the existing ack comment (don't lose feedback)."""
    _setup_env(monkeypatch, comment_id="12345")
    issue = _FakeIssue(labels=["needs-human"])
    from flow.handlers import comment_handler as mod

    gh = _patch_handler(monkeypatch, issue, react_succeeds=False)
    rc = mod.handle_comment_created()

    assert rc == 0
    gh.react_to_comment.assert_called_once()
    # Must have fallen back to a comment ack
    assert gh.comment.call_count == 1


def test_missing_comment_id_falls_back_to_comment(monkeypatch):
    """Older workflow versions without FLOW_COMMENT_ID still work."""
    _setup_env(monkeypatch, comment_id=None)
    issue = _FakeIssue(labels=["needs-human"])
    from flow.handlers import comment_handler as mod

    gh = _patch_handler(monkeypatch, issue, react_succeeds=True)
    rc = mod.handle_comment_created()

    assert rc == 0
    gh.react_to_comment.assert_not_called()
    assert gh.comment.call_count == 1


def test_invalid_state_transition_still_posts_explanatory_comment(monkeypatch):
    """When the command is rejected by state machine, an emoji isn't
    informative — must still post a comment explaining why."""
    _setup_env(monkeypatch, comment_id="12345")
    monkeypatch.setenv("FLOW_COMMENT_BODY", "/agent retry")
    # agent-done is terminal → /agent retry rejected
    issue = _FakeIssue(labels=["agent-done"])
    from flow.handlers import comment_handler as mod

    gh = _patch_handler(monkeypatch, issue, react_succeeds=True)
    rc = mod.handle_comment_created()

    assert rc == 0
    # No reaction (rejection isn't an OK)
    gh.react_to_comment.assert_not_called()
    # Explanatory comment posted
    assert gh.comment.call_count == 1
    posted = gh.comment.call_args.args[1]
    assert "不接受" in posted or "not accept" in posted.lower()


@pytest.mark.parametrize("malformed", ["", "abc", "  "])
def test_malformed_comment_id_falls_back(monkeypatch, malformed):
    _setup_env(monkeypatch, comment_id=malformed)
    issue = _FakeIssue(labels=["needs-human"])
    from flow.handlers import comment_handler as mod

    gh = _patch_handler(monkeypatch, issue, react_succeeds=True)
    rc = mod.handle_comment_created()

    assert rc == 0
    # Empty/whitespace skips the reaction path entirely; non-int strings
    # raise ValueError and also fall back.
    assert gh.comment.call_count == 1
