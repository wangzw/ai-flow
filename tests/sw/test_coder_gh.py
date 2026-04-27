from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sw.coder_gh import CoderResult, run_coder_gh


@pytest.fixture
def fake_repo():
    repo = MagicMock()
    repo.default_branch = "main"
    repo.full_name = "owner/name"
    repo.clone_url = "https://github.com/owner/name.git"

    issue = MagicMock()
    issue.body = "## AC\n<!-- ac:start -->\nDo X\n<!-- ac:end -->"
    issue.title = "test"
    issue.number = 42
    repo.get_issue.return_value = issue

    pr = MagicMock()
    pr.number = 100
    repo.create_pull.return_value = pr

    return repo


def test_run_coder_gh_done_creates_pr(fake_repo, tmp_path):
    """Happy path: copilot returns done; coder pushes & opens draft PR."""
    cli = MagicMock()
    cli.run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        review_dir = Path(to_path) / ".agent"
        review_dir.mkdir()
        (review_dir / "result.yaml").write_text("status: done\nsummary: did X\n")
        return MagicMock()

    with patch("sw.coder_gh._clone_repo", side_effect=fake_clone), \
         patch("sw.coder_gh._push_branch") as push:
        result = run_coder_gh(
            repo=fake_repo,
            issue_number=42,
            issue_title="test",
            cli=cli,
            workdir=tmp_path,
        )

    assert isinstance(result, CoderResult)
    assert result.success is True
    assert result.mr_iid == 100  # pr.number
    cli.run.assert_called_once()
    push.assert_called_once()
    # PR is created with draft=True
    fake_repo.create_pull.assert_called_once()
    kwargs = fake_repo.create_pull.call_args.kwargs
    assert kwargs.get("draft") is True
    assert kwargs.get("base") == "main"
    assert "Closes #42" in kwargs.get("body", "")


def test_run_coder_gh_blocked_returns_blocker(fake_repo, tmp_path):
    cli = MagicMock()
    cli.run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        review_dir = Path(to_path) / ".agent"
        review_dir.mkdir()
        (review_dir / "result.yaml").write_text(
            "status: blocked\n"
            "blocker_type: ac_ambiguity\n"
            "question: 'How?'\n"
            "options:\n"
            "  - id: a\n"
        )
        return MagicMock()

    with patch("sw.coder_gh._clone_repo", side_effect=fake_clone), \
         patch("sw.coder_gh._push_branch"):
        result = run_coder_gh(
            repo=fake_repo,
            issue_number=42,
            issue_title="t",
            cli=cli,
            workdir=tmp_path,
        )

    assert result.success is False
    assert result.blocker is not None
    assert result.blocker["blocker_type"] == "ac_ambiguity"
    fake_repo.create_pull.assert_not_called()


def test_run_coder_gh_subprocess_error_returns_blocker(fake_repo, tmp_path):
    cli = MagicMock()
    cli.run.return_value = MagicMock(returncode=1, stdout="", stderr="quota")

    with patch("sw.coder_gh._clone_repo", return_value=MagicMock()), \
         patch("sw.coder_gh._push_branch"):
        result = run_coder_gh(
            repo=fake_repo,
            issue_number=42,
            issue_title="t",
            cli=cli,
            workdir=tmp_path,
        )

    assert result.success is False
    assert result.blocker["blocker_type"] == "subprocess_error"


def test_run_coder_gh_missing_marker_returns_blocker(fake_repo, tmp_path):
    cli = MagicMock()
    cli.run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        return MagicMock()

    with patch("sw.coder_gh._clone_repo", side_effect=fake_clone), \
         patch("sw.coder_gh._push_branch"):
        result = run_coder_gh(
            repo=fake_repo,
            issue_number=42,
            issue_title="t",
            cli=cli,
            workdir=tmp_path,
        )

    assert result.success is False
    assert result.blocker["blocker_type"] == "no_result_marker"
