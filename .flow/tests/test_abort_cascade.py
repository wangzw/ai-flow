"""/agent abort cascade behavior.

When abort is issued on a Goal, all non-terminal child tasks must be
cancelled (label = agent-failed, issue closed) and their open PRs closed.
When abort is issued on a Task, its open PRs must be closed.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from flow.manifest import (
    GoalAgentState,
    GoalBody,
    ManifestEntry,
    ReviewState,
    TaskAgentState,
    TaskBody,
    TaskSpec,
)


class _FakeLabel:
    def __init__(self, name: str):
        self.name = name


def _make_issue(*, number, labels, body, state="open", is_pr=False):
    obj = MagicMock()
    obj.number = number
    obj.labels = [_FakeLabel(n) for n in labels]
    obj.body = body
    obj.state = state
    obj.create_comment = MagicMock()
    obj.edit = MagicMock(side_effect=lambda **kw: setattr(obj, "state", kw.get("state", obj.state)))
    if is_pr:
        # PRs in PyGithub also have .edit(state="closed")
        pass
    return obj


def _make_goal_body(children):
    """children: list of (issue_num, task_id, state)."""
    gb = GoalBody(
        manifest=[
            ManifestEntry(task_id=tid, issue=n, deps=[], state=st)
            for (n, tid, st) in children
        ],
        agent_state=GoalAgentState(),
        prose="goal",
    )
    return gb.to_body()


def _make_task_body(*, task_id, goal_issue, pr_num=None):
    tb = TaskBody(
        task_id=task_id,
        goal_issue=goal_issue,
        spec=TaskSpec(goal="g", quality_criteria=["q"]),
        deps=[],
        agent_state=TaskAgentState(),
        review=ReviewState(),
        artifacts=([{"pr": pr_num, "branch": "b"}] if pr_num else []),
        prose="task",
    )
    return tb.to_body()


def _setup(monkeypatch, *, comment_body):
    monkeypatch.setenv("FLOW_REPO", "owner/repo")
    monkeypatch.setenv("FLOW_ISSUE_NUMBER", "100")
    monkeypatch.setenv("FLOW_COMMENT_BODY", comment_body)
    monkeypatch.setenv("FLOW_COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("FLOW_COMMENT_ID", "9999")


def _patch(monkeypatch, repo_mock):
    import flow.handlers.comment_handler as mod

    gh = MagicMock()
    gh.get_repo.return_value = repo_mock
    gh.react_to_comment.return_value = True

    monkeypatch.setattr(mod.GitHubClient, "from_env", classmethod(lambda cls: gh))
    monkeypatch.setattr(mod, "is_authorized", lambda *a, **kw: True)

    fake_cfg = MagicMock()
    fake_cfg.authorized_users = ["alice"]
    monkeypatch.setattr(mod.Config, "load", classmethod(lambda cls: fake_cfg))
    return gh, mod


def test_goal_abort_cascades_to_tasks_and_prs(monkeypatch):
    _setup(monkeypatch, comment_body="/agent abort")

    goal_body = _make_goal_body([
        (101, "T-a", "agent-working"),
        (102, "T-b", "needs-human"),
        (103, "T-c", "agent-done"),  # already terminal — must skip
    ])
    goal = _make_issue(number=100, labels=["type:goal", "agent-working"], body=goal_body)

    task_a = _make_issue(number=101, labels=["type:task", "agent-working"],
                        body=_make_task_body(task_id="T-a", goal_issue=100, pr_num=201))
    task_b = _make_issue(number=102, labels=["type:task", "needs-human"],
                        body=_make_task_body(task_id="T-b", goal_issue=100))
    task_c = _make_issue(number=103, labels=["type:task", "agent-done"],
                        body=_make_task_body(task_id="T-c", goal_issue=100, pr_num=203))

    pr_201 = MagicMock()
    pr_201.state = "open"
    pr_201.edit = MagicMock(
        side_effect=lambda **kw: setattr(pr_201, "state", kw.get("state", pr_201.state))
    )

    repo = MagicMock()
    repo.get_issue = MagicMock(
        side_effect=lambda n: {100: goal, 101: task_a, 102: task_b, 103: task_c}[n]
    )
    repo.get_pull = MagicMock(side_effect=lambda n: {201: pr_201}[n])

    gh, mod = _patch(monkeypatch, repo)
    rc = mod.handle_comment_created()
    assert rc == 0

    # Open PR for non-terminal child closed; terminal child untouched.
    assert pr_201.state == "closed"
    repo.get_pull.assert_called_once_with(201)  # task_c's PR NOT touched

    # Non-terminal children cancelled (agent-failed) and closed.
    failed_calls = [c for c in gh.set_state_label.call_args_list
                    if c.args[1] == "agent-failed"]
    failed_targets = {c.args[0].number for c in failed_calls}
    assert 101 in failed_targets and 102 in failed_targets
    assert 103 not in failed_targets  # already terminal

    assert task_a.state == "closed"
    assert task_b.state == "closed"
    # Goal itself transitions to agent-failed and closes.
    assert any(c.args[1] == "agent-failed" and c.args[0] is goal
               for c in gh.set_state_label.call_args_list)
    assert goal.state == "closed"

    # Cascade comment posted on each affected child + summary on goal.
    commented_targets = [c.args[0] for c in gh.comment.call_args_list]
    assert task_a in commented_targets
    assert task_b in commented_targets
    assert task_c not in commented_targets
    assert goal in commented_targets


def test_task_abort_closes_open_pr(monkeypatch):
    _setup(monkeypatch, comment_body="/agent abort")
    monkeypatch.setenv("FLOW_ISSUE_NUMBER", "200")

    task = _make_issue(
        number=200, labels=["type:task", "agent-working"],
        body=_make_task_body(task_id="T-x", goal_issue=100, pr_num=301),
    )
    pr_301 = MagicMock()
    pr_301.state = "open"
    pr_301.edit = MagicMock(
        side_effect=lambda **kw: setattr(pr_301, "state", kw.get("state", pr_301.state))
    )

    repo = MagicMock()
    repo.get_issue = MagicMock(return_value=task)
    repo.get_pull = MagicMock(return_value=pr_301)

    gh, mod = _patch(monkeypatch, repo)
    rc = mod.handle_comment_created()
    assert rc == 0

    assert pr_301.state == "closed"
    assert task.state == "closed"
    assert any(c.args[1] == "agent-failed" for c in gh.set_state_label.call_args_list)
    # Comment posted explaining the PR was closed
    assert any(c.args[0] is task for c in gh.comment.call_args_list)


def test_goal_abort_with_no_children_still_closes_goal(monkeypatch):
    _setup(monkeypatch, comment_body="/agent abort")
    goal_body = _make_goal_body([])
    goal = _make_issue(number=100, labels=["type:goal", "agent-working"], body=goal_body)
    repo = MagicMock()
    repo.get_issue = MagicMock(return_value=goal)

    gh, mod = _patch(monkeypatch, repo)
    rc = mod.handle_comment_created()
    assert rc == 0
    assert goal.state == "closed"
    assert any(c.args[1] == "agent-failed" for c in gh.set_state_label.call_args_list)
