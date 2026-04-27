from unittest.mock import MagicMock

from sw.handlers.mr_handler import handle_mr_ready


def test_all_pass_merges_and_marks_issue_done():
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.description = "Closes #42"
    project.mergerequests.get.return_value = mr

    issue = MagicMock()
    issue.labels = ["agent-working"]
    issue.iid = 42
    project.issues.get.return_value = issue

    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))
    client = MagicMock()

    handle_mr_ready(
        project=project,
        mr_iid=100,
        client=client,
        reviewer=reviewer,
    )

    mr.merge.assert_called_once()
    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-done" in labels


def test_any_fail_does_not_merge_and_keeps_working():
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.description = "Closes #42"
    project.mergerequests.get.return_value = mr

    issue = MagicMock()
    issue.labels = ["agent-working"]
    issue.iid = 42
    project.issues.get.return_value = issue

    reviewer = MagicMock(return_value=MagicMock(all_passed=False, failed_dimensions=["security"]))
    client = MagicMock()

    handle_mr_ready(
        project=project,
        mr_iid=100,
        client=client,
        reviewer=reviewer,
    )

    mr.merge.assert_not_called()
    client.set_state_label.assert_not_called()


def test_extracts_issue_iid_from_description_closes_pattern():
    from sw.handlers.mr_handler import _extract_closing_issue_iid

    assert _extract_closing_issue_iid("Closes #42") == 42
    assert _extract_closing_issue_iid("- closes #99\nstuff") == 99
    assert _extract_closing_issue_iid("see issue 42") is None


def test_all_pass_but_no_closes_pattern_does_not_touch_issue():
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.description = "no closes pattern here"
    project.mergerequests.get.return_value = mr

    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))
    client = MagicMock()

    handle_mr_ready(project=project, mr_iid=100, client=client, reviewer=reviewer)

    mr.merge.assert_called_once()  # MR still merges
    project.issues.get.assert_not_called()
    client.set_state_label.assert_not_called()
