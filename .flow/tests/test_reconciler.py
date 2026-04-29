"""Reconciler tests using a fake GitHub client (no network)."""
from __future__ import annotations

from dataclasses import dataclass, field

from flow.manifest import GoalBody, ManifestEntry, TaskBody, TaskSpec
from flow.reconciler import CurrentChild, reconcile

# ---------- Fakes ----------

class FakeIssue:
    def __init__(self, number: int, title: str = "", body: str = "", labels=()):
        self.number = number
        self.title = title
        self.body = body
        self.labels = [type("L", (), {"name": n})() for n in labels]
        self.state = "open"

    def edit(self, body: str | None = None, state: str | None = None):
        if body is not None:
            self.body = body
        if state is not None:
            self.state = state


class FakeRepo:
    def __init__(self):
        self.issues: dict[int, FakeIssue] = {}
        self.next_id = 100
        self.full_name = "owner/repo"
        self.default_branch = "main"

    def create_issue(self, title, body, labels):
        n = self.next_id
        self.next_id += 1
        issue = FakeIssue(number=n, title=title, body=body, labels=labels)
        self.issues[n] = issue
        return issue

    def get_issue(self, num):
        return self.issues[num]


class FakeGhClient:
    def __init__(self):
        self.calls: list[tuple] = []

    def set_state_label(self, issue, state):
        # remove existing state labels
        from flow.state_machine import EXTERNAL_STATES
        new = [lbl for lbl in issue.labels if lbl.name not in EXTERNAL_STATES]
        new.append(type("L", (), {"name": state})())
        issue.labels = new
        self.calls.append(("set_state_label", issue.number, state))

    def comment(self, issue, body):
        self.calls.append(("comment", issue.number, body[:80]))
        cid = 9000 + len(self.calls)
        return type("C", (), {"id": cid, "body": body})()

    def upsert_comment(self, issue, comment_id, body):
        if comment_id is not None:
            self.calls.append(("update_comment", issue.number, comment_id, body[:80]))
            return type("C", (), {"id": comment_id, "body": body})()
        return self.comment(issue, body)

    def update_issue_body(self, issue, body):
        issue.body = body
        self.calls.append(("update_issue_body", issue.number))

    def create_issue(self, repo, *, title, body, labels):
        issue = repo.create_issue(title=title, body=body, labels=labels)
        self.calls.append(("create_issue", issue.number, title))
        return issue

    def close_issue(self, issue):
        issue.state = "closed"
        self.calls.append(("close_issue", issue.number))


@dataclass
class FakePlannerResult:
    status: str
    desired_plan: list[dict] = field(default_factory=list)
    actions: dict = field(default_factory=dict)
    summary: str = ""
    blocker: dict | None = None


# ---------- Tests ----------

def _make_goal(repo: FakeRepo) -> tuple[FakeIssue, GoalBody]:
    gb = GoalBody(prose="root goal")
    issue = FakeIssue(number=1, title="Goal",
                      body=gb.to_body(),
                      labels=["type:goal", "agent-working"])
    repo.issues[1] = issue
    return issue, gb


def test_reconcile_creates_new_tasks():
    repo = FakeRepo()
    gh = FakeGhClient()
    issue, gb = _make_goal(repo)
    result = FakePlannerResult(
        status="ok",
        desired_plan=[
            {"task_id": "T-a", "spec": {"goal": "do A", "quality_criteria": ["x"]},
             "deps": []},
            {"task_id": "T-b", "spec": {"goal": "do B"}, "deps": ["T-a"]},
        ],
    )
    reconcile(planner_result=result, repo=repo, goal_issue=issue, goal_body=gb,
              current_children=[], client=gh)
    # 2 issues created
    create_calls = [c for c in gh.calls if c[0] == "create_issue"]
    assert len(create_calls) == 2
    # manifest now has 2 entries
    refreshed = GoalBody.parse(issue.body)
    assert len(refreshed.manifest) == 2
    assert {m.task_id for m in refreshed.manifest} == {"T-a", "T-b"}


def test_reconcile_cancels_orphans():
    repo = FakeRepo()
    gh = FakeGhClient()
    issue, gb = _make_goal(repo)
    # Pre-existing child T-old
    child = FakeIssue(number=200, body=TaskBody(task_id="T-old",
                                                spec=TaskSpec(goal="old")).to_body(),
                      labels=["type:task", "agent-working"])
    repo.issues[200] = child
    gb.manifest.append(ManifestEntry(task_id="T-old", issue=200, state="agent-working"))
    issue.body = gb.to_body()

    current = [CurrentChild(issue=child, task_id="T-old", state_label="agent-working",
                            body=TaskBody.parse(child.body))]
    result = FakePlannerResult(status="ok", desired_plan=[
        {"task_id": "T-new", "spec": {"goal": "new"}, "deps": []},
    ])
    reconcile(planner_result=result, repo=repo, goal_issue=issue, goal_body=gb,
              current_children=current, client=gh)
    # T-old must be cancelled (set to agent-failed)
    cancel_calls = [c for c in gh.calls
                    if c[0] == "set_state_label" and c[1] == 200 and c[2] == "agent-failed"]
    assert cancel_calls, "expected T-old to be cancelled"
    # T-new should be created
    assert any(c[0] == "create_issue" for c in gh.calls)


def test_false_done_blocked():
    """Hard guard: status=done with non-terminal children must NOT close goal."""
    repo = FakeRepo()
    gh = FakeGhClient()
    issue, gb = _make_goal(repo)
    child = FakeIssue(number=300, labels=["type:task", "agent-working"],
                      body=TaskBody(task_id="T-a").to_body())
    current = [CurrentChild(issue=child, task_id="T-a", state_label="agent-working",
                            body=TaskBody.parse(child.body))]
    result = FakePlannerResult(status="done", summary="all good")
    reconcile(planner_result=result, repo=repo, goal_issue=issue, goal_body=gb,
              current_children=current, client=gh)
    # Should set needs-human, not close
    nh_calls = [c for c in gh.calls
                if c[0] == "set_state_label" and c[2] == "needs-human"]
    assert nh_calls
    assert issue.state != "closed"


def test_done_closes_goal():
    repo = FakeRepo()
    gh = FakeGhClient()
    issue, gb = _make_goal(repo)
    result = FakePlannerResult(status="done", summary="✅")
    reconcile(planner_result=result, repo=repo, goal_issue=issue, goal_body=gb,
              current_children=[], client=gh)
    assert issue.state == "closed"
    done_calls = [c for c in gh.calls if c[0] == "set_state_label" and c[2] == "agent-done"]
    assert done_calls


def test_blocked_emits_needs_human():
    repo = FakeRepo()
    gh = FakeGhClient()
    issue, gb = _make_goal(repo)
    result = FakePlannerResult(
        status="blocked",
        blocker={"question": "DB?",
                 "options": [{"id": "pg", "desc": "Postgres"}],
                 "agent_state": {"stage": "planner", "blocker_type": "goal_too_vague"}},
    )
    reconcile(planner_result=result, repo=repo, goal_issue=issue, goal_body=gb,
              current_children=[], client=gh)
    nh_calls = [c for c in gh.calls
                if c[0] == "set_state_label" and c[2] == "needs-human"]
    assert nh_calls
