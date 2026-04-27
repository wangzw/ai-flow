from unittest.mock import MagicMock

from sw.merge_queue_gh import process_merge_queue_gh


def _label(name: str):
    lbl = MagicMock()
    lbl.name = name
    return lbl


def _pr(number, labels=("merge-queued",), body="Closes #5"):
    pr = MagicMock()
    pr.number = number
    pr.labels = [_label(name) for name in labels]
    pr.body = body
    pr.created_at = "2026-04-01T00:00:00Z"
    return pr


def test_empty_queue_processes_zero():
    repo = MagicMock()
    repo.get_pulls.return_value = []
    n = process_merge_queue_gh(repo=repo, client=MagicMock(), reviewer=MagicMock())
    assert n == 0


def test_queue_pop_all_pass_merges_and_marks_issue_done():
    repo = MagicMock()
    pr = _pr(100)
    repo.get_pulls.return_value = [pr]

    issue = MagicMock()
    repo.get_issue.return_value = issue
    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    n = process_merge_queue_gh(repo=repo, client=client, reviewer=reviewer)

    assert n == 1
    pr.merge.assert_called_once()
    # called with rebase merge method
    assert pr.merge.call_args.kwargs.get("merge_method") == "rebase"
    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-done" in labels


def test_queue_pop_review_fail_dequeues_and_resets_to_working():
    repo = MagicMock()
    pr = _pr(100)
    repo.get_pulls.return_value = [pr]

    issue = MagicMock()
    repo.get_issue.return_value = issue
    client = MagicMock()
    reviewer = MagicMock(
        return_value=MagicMock(all_passed=False, failed_dimensions=["security"])
    )

    n = process_merge_queue_gh(repo=repo, client=client, reviewer=reviewer)

    assert n == 1
    pr.merge.assert_not_called()
    pr.remove_from_labels.assert_called_once_with("merge-queued")
    set_calls = client.set_state_label.call_args_list
    labels = [c.kwargs.get("new_label") or c.args[1] for c in set_calls]
    assert "agent-working" in labels


def test_queue_processes_fifo_only_first():
    repo = MagicMock()
    older = _pr(50)
    older.created_at = "2026-01-01T00:00:00Z"
    newer = _pr(100)
    newer.created_at = "2026-02-01T00:00:00Z"
    repo.get_pulls.return_value = [newer, older]

    repo.get_issue.return_value = MagicMock()
    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    n = process_merge_queue_gh(repo=repo, client=client, reviewer=reviewer)

    assert n == 1
    older.merge.assert_called_once()
    newer.merge.assert_not_called()


def test_queue_filters_open_with_merge_queued_label_only():
    """PRs without the merge-queued label are not picked up."""
    repo = MagicMock()
    not_queued = _pr(50, labels=("bug",))
    queued = _pr(100, labels=("merge-queued",))
    repo.get_pulls.return_value = [not_queued, queued]

    repo.get_issue.return_value = MagicMock()
    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    n = process_merge_queue_gh(repo=repo, client=client, reviewer=reviewer)

    assert n == 1
    queued.merge.assert_called_once()
    not_queued.merge.assert_not_called()


def test_no_closes_pattern_skips_issue_update_on_pass():
    repo = MagicMock()
    pr = _pr(100, body="no closes pattern here")
    repo.get_pulls.return_value = [pr]

    client = MagicMock()
    reviewer = MagicMock(return_value=MagicMock(all_passed=True, failed_dimensions=[]))

    n = process_merge_queue_gh(repo=repo, client=client, reviewer=reviewer)

    assert n == 1
    pr.merge.assert_called_once()
    repo.get_issue.assert_not_called()
    client.set_state_label.assert_not_called()
