from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sw.coder import run_coder


@pytest.fixture
def fake_project():
    project = MagicMock()
    project.default_branch = "main"
    project.path_with_namespace = "g/r"
    project.http_url_to_repo = "https://gitlab.example/g/r.git"
    issue = MagicMock()
    issue.description = "## AC\n<!-- ac:start -->\nDo X\n<!-- ac:end -->"
    issue.title = "test"
    project.issues.get.return_value = issue
    mr = MagicMock()
    mr.iid = 100
    project.mergerequests.create.return_value = mr
    return project


def test_run_coder_done_creates_mr(fake_project, tmp_path):
    """Happy path: Claude Code returns done; coder pushes & opens MR."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        result_dir = Path(to_path) / ".agent"
        result_dir.mkdir()
        (result_dir / "result.yaml").write_text("status: done\nsummary: implemented X\n")
        return MagicMock()

    with patch("sw.coder._clone_repo", side_effect=fake_clone), \
         patch("sw.coder._push_branch") as push:
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is True
    assert result.mr_iid == 100
    cc.run.assert_called_once()
    push.assert_called_once()
    fake_project.mergerequests.create.assert_called_once()


def test_run_coder_blocked_returns_blocker(fake_project, tmp_path):
    """Claude Code marker says blocked → no MR, blocker payload returned."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        result_dir = Path(to_path) / ".agent"
        result_dir.mkdir()
        (result_dir / "result.yaml").write_text(
            "status: blocked\n"
            "blocker_type: ac_ambiguity\n"
            "question: 'How to handle X?'\n"
            "options:\n"
            "  - id: a\n"
            "  - id: b\n"
        )
        return MagicMock()

    with patch("sw.coder._clone_repo", side_effect=fake_clone), \
         patch("sw.coder._push_branch"):
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is False
    assert result.blocker is not None
    assert result.blocker["blocker_type"] == "ac_ambiguity"
    fake_project.mergerequests.create.assert_not_called()


def test_run_coder_subprocess_error_returns_blocker(fake_project, tmp_path):
    """Claude Code subprocess error → blocker."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=1, stdout="", stderr="rate limit")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        return MagicMock()

    with patch("sw.coder._clone_repo", side_effect=fake_clone), \
         patch("sw.coder._push_branch"):
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is False
    assert result.blocker["blocker_type"] == "subprocess_error"


def test_run_coder_missing_marker_returns_blocker(fake_project, tmp_path):
    """No marker file written → blocker."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    def fake_clone(url, to_path, branch=None):
        Path(to_path).mkdir(parents=True, exist_ok=True)
        return MagicMock()

    with patch("sw.coder._clone_repo", side_effect=fake_clone), \
         patch("sw.coder._push_branch"):
        result = run_coder(
            project=fake_project,
            issue_iid=42,
            issue_title="test",
            claude=cc,
            workdir=tmp_path,
        )
    assert result.success is False
    assert result.blocker["blocker_type"] == "no_result_marker"
