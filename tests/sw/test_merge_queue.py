from unittest.mock import MagicMock

import pytest

from sw.merge_queue import MergeQueueError, process_merge_queue


def _mr(iid, labels=("merge-queued",), description="Closes #5", rebase_states=(False,)):
    """rebase_states: sequence of rebase_in_progress values returned across refreshes."""
    mr = MagicMock()
    mr.iid = iid
    mr.labels = list(labels)
    mr.description = description
    mr.rebase_in_progress = rebase_states[0]
    mr._states = list(rebase_states)
    return mr


def test_empty_queue_processes_zero():
    project = MagicMock()
    project.mergerequests.list.return_value = []
    n = process_merge_queue(project=project, client=MagicMock(), reviewer=MagicMock())
    assert n == 0


def test_queue_pop_all_pass_merges_and_marks_issue_done():
    project = MagicMock()
    mr = _mr(100)
    project.mergerequests.list.return_value = [mr]
    project.mergerequests.get.return_value = mr  # refresh returns the same

    issue = MagicMock()
    project.issues.get.return_value = issue
    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    n = process_merge_queue(
        project=project, client=client, reviewer=reviewer, sleep=lambda *_: None
    )

    assert n == 1
    mr.rebase.assert_called_once()
    mr.merge.assert_called_once()
    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-done" in labels


def test_queue_pop_review_fail_dequeues_and_resets_to_working():
    project = MagicMock()
    mr = _mr(100)
    project.mergerequests.list.return_value = [mr]
    project.mergerequests.get.return_value = mr

    issue = MagicMock()
    project.issues.get.return_value = issue
    client = MagicMock()
    reviewer = MagicMock(
        return_value=MagicMock(all_passed=False, failed_dimensions=["security"])
    )

    n = process_merge_queue(
        project=project, client=client, reviewer=reviewer, sleep=lambda *_: None
    )

    assert n == 1
    mr.merge.assert_not_called()
    # merge-queued label removed
    assert "merge-queued" not in mr.labels
    mr.save.assert_called()
    # issue reset to agent-working
    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-working" in labels


def test_queue_processes_fifo_only_first():
    """Two MRs queued: only the FIFO-first is processed in this call."""
    project = MagicMock()
    older = _mr(50)
    older.created_at = "2026-01-01T00:00:00Z"
    newer = _mr(100)
    newer.created_at = "2026-02-01T00:00:00Z"
    project.mergerequests.list.return_value = [newer, older]  # unsorted
    project.mergerequests.get.return_value = older

    project.issues.get.return_value = MagicMock()
    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    n = process_merge_queue(
        project=project, client=client, reviewer=reviewer, sleep=lambda *_: None
    )

    assert n == 1
    older.merge.assert_called_once()
    newer.merge.assert_not_called()


def test_rebase_poll_waits_until_complete():
    """rebase_in_progress True → True → False; we poll until False."""
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.labels = ["merge-queued"]
    mr.description = "Closes #5"

    # First the list returns mr; refresh repeats sequence in rebase_in_progress
    states = iter([True, True, False])

    def fake_get(iid):
        # Each refresh returns a "fresh" copy with the next rebase state
        fresh = MagicMock()
        fresh.iid = mr.iid
        fresh.labels = mr.labels
        fresh.description = mr.description
        fresh.rebase_in_progress = next(states)
        # Forward merge etc to original mr for assertion later
        fresh.merge = mr.merge
        fresh.rebase = mr.rebase
        fresh.save = mr.save
        return fresh

    project.mergerequests.list.return_value = [mr]
    project.mergerequests.get.side_effect = fake_get

    project.issues.get.return_value = MagicMock()
    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    sleep_calls = []
    process_merge_queue(
        project=project, client=client, reviewer=reviewer,
        sleep=lambda s: sleep_calls.append(s),
    )

    # We polled at least twice while rebase_in_progress was True
    assert len(sleep_calls) >= 2
    mr.merge.assert_called_once()


def test_rebase_timeout_raises():
    """rebase_in_progress stays True forever → timeout raises MergeQueueError."""
    project = MagicMock()
    mr = MagicMock()
    mr.iid = 100
    mr.labels = ["merge-queued"]

    def always_in_progress(iid):
        fresh = MagicMock()
        fresh.iid = mr.iid
        fresh.labels = mr.labels
        fresh.rebase_in_progress = True
        return fresh

    project.mergerequests.list.return_value = [mr]
    project.mergerequests.get.side_effect = always_in_progress

    with pytest.raises(MergeQueueError, match="rebase"):
        process_merge_queue(
            project=project, client=MagicMock(), reviewer=MagicMock(),
            sleep=lambda *_: None,
            rebase_timeout=0.05,
            rebase_poll_interval=0.01,
        )


def test_no_closes_pattern_skips_issue_update_on_pass():
    project = MagicMock()
    mr = _mr(100, description="no closes here")
    project.mergerequests.list.return_value = [mr]
    project.mergerequests.get.return_value = mr

    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    n = process_merge_queue(
        project=project, client=client, reviewer=reviewer, sleep=lambda *_: None
    )

    assert n == 1
    mr.merge.assert_called_once()
    project.issues.get.assert_not_called()
    client.set_state_label.assert_not_called()
