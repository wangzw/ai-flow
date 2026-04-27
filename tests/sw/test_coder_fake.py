from unittest.mock import MagicMock

from sw.coder_stub import CoderResult, run_coder


def test_run_coder_creates_branch_and_mr():
    project = MagicMock()
    project.default_branch = "main"
    project.path_with_namespace = "g/r"

    branch = MagicMock()
    branch.name = "agent/issue-42"
    project.branches.create.return_value = branch

    project.commits.create.return_value = MagicMock()

    mr = MagicMock()
    mr.iid = 100
    project.mergerequests.create.return_value = mr

    result = run_coder(project=project, issue_iid=42, issue_title="test")

    assert isinstance(result, CoderResult)
    assert result.success is True
    assert result.mr_iid == 100
    project.branches.create.assert_called_once()
    project.commits.create.assert_called_once()
    project.mergerequests.create.assert_called_once()


def test_branch_name_includes_issue_iid():
    project = MagicMock()
    project.default_branch = "main"
    branch = MagicMock()
    branch.name = "agent/issue-42"
    project.branches.create.return_value = branch
    project.mergerequests.create.return_value = MagicMock(iid=1)

    run_coder(project=project, issue_iid=42, issue_title="t")

    call_args = project.branches.create.call_args[0][0]
    assert "42" in call_args["branch"]
    assert call_args["ref"] == "main"


def test_mr_is_draft():
    project = MagicMock()
    project.default_branch = "main"
    project.branches.create.return_value = MagicMock(name="agent/issue-1")
    project.mergerequests.create.return_value = MagicMock(iid=1)

    run_coder(project=project, issue_iid=1, issue_title="t")

    mr_args = project.mergerequests.create.call_args[0][0]
    title = mr_args["title"]
    assert title.startswith("Draft:") or mr_args.get("draft") is True
