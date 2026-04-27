from unittest.mock import MagicMock

from sw.handlers.mr_handler import handle_mr_ready


def test_all_pass_enqueues_via_merge_queued_label():
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.description = "Closes #42"
    mr.labels = []
    project.mergerequests.get.return_value = mr

    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))
    client = MagicMock()

    handle_mr_ready(
        project=project,
        mr_iid=100,
        client=client,
        reviewer=reviewer,
    )

    assert "merge-queued" in mr.labels
    mr.save.assert_called_once()
    mr.merge.assert_not_called()  # merge happens in queue processor, not here
    client.set_state_label.assert_not_called()  # Issue label transition happens after queue pop


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


def test_all_pass_but_no_closes_pattern_still_enqueues():
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.description = "no closes pattern here"
    mr.labels = []
    project.mergerequests.get.return_value = mr

    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))
    client = MagicMock()

    handle_mr_ready(project=project, mr_iid=100, client=client, reviewer=reviewer)

    assert "merge-queued" in mr.labels
    mr.merge.assert_not_called()
    project.issues.get.assert_not_called()
