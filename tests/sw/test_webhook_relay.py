import pytest

from sw.webhook_relay import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GITLAB_API_TOKEN", "fake-token")
    monkeypatch.setenv("WEBHOOK_SECRET", "shared-secret")
    app = create_app()
    return app.test_client()


def _post(client, payload, headers=None):
    h = {"X-Gitlab-Token": "shared-secret", **(headers or {})}
    return client.post("/webhook", json=payload, headers=h)


def test_rejects_missing_token(client):
    resp = client.post("/webhook", json={})
    assert resp.status_code == 401


def test_rejects_wrong_token(client):
    resp = client.post("/webhook", json={}, headers={"X-Gitlab-Token": "wrong"})
    assert resp.status_code == 401


def test_label_added_triggers_pipeline(client, monkeypatch):
    triggered = {}

    def fake_trigger(project_path, ref, variables):
        triggered.update(project_path=project_path, ref=ref, variables=variables)

    monkeypatch.setattr("sw.webhook_relay._trigger_pipeline", fake_trigger)

    payload = {
        "object_kind": "issue",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "object_attributes": {"iid": 42, "action": "update"},
        "changes": {"labels": {"previous": [], "current": [{"title": "agent-ready"}]}},
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert triggered["variables"]["CI_TRIGGERED_EVENT"] == "issue_label_added"
    assert triggered["variables"]["SW_ISSUE_IID"] == "42"
    assert triggered["variables"]["SW_LABEL_ADDED"] == "agent-ready"


def test_note_added_on_issue_triggers_pipeline(client, monkeypatch):
    triggered = {}
    monkeypatch.setattr(
        "sw.webhook_relay._trigger_pipeline",
        lambda **kw: triggered.update(**kw),
    )

    payload = {
        "object_kind": "note",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "issue": {"iid": 42},
        "object_attributes": {"note": "/agent resume", "noteable_type": "Issue"},
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert triggered["variables"]["CI_TRIGGERED_EVENT"] == "issue_note_added"
    assert triggered["variables"]["SW_COMMENT_BODY"] == "/agent resume"


def test_mr_ready_triggers_pipeline(client, monkeypatch):
    triggered = {}
    monkeypatch.setattr(
        "sw.webhook_relay._trigger_pipeline",
        lambda **kw: triggered.update(**kw),
    )
    payload = {
        "object_kind": "merge_request",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "object_attributes": {
            "iid": 100,
            "action": "update",
            "oldrev": None,
            "work_in_progress": False,
        },
        "changes": {"draft": {"previous": True, "current": False}},
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert triggered["variables"]["CI_TRIGGERED_EVENT"] == "mr_ready"
    assert triggered["variables"]["SW_MR_IID"] == "100"


def test_unrelated_event_is_no_op(client, monkeypatch):
    called = []
    monkeypatch.setattr("sw.webhook_relay._trigger_pipeline", lambda **kw: called.append(kw))

    payload = {"object_kind": "push", "project": {"path_with_namespace": "g/r"}}
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert called == []


def test_label_added_with_multiple_including_agent_ready(client, monkeypatch):
    triggered = {}
    monkeypatch.setattr(
        "sw.webhook_relay._trigger_pipeline",
        lambda **kw: triggered.update(**kw),
    )
    payload = {
        "object_kind": "issue",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "object_attributes": {"iid": 42, "action": "update"},
        "changes": {
            "labels": {
                "previous": [],
                "current": [{"title": "bug"}, {"title": "agent-ready"}, {"title": "p1"}],
            }
        },
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert triggered["variables"]["SW_LABEL_ADDED"] == "agent-ready"


def test_label_added_without_agent_ready_does_not_trigger(client, monkeypatch):
    called = []
    monkeypatch.setattr(
        "sw.webhook_relay._trigger_pipeline",
        lambda **kw: called.append(kw),
    )
    payload = {
        "object_kind": "issue",
        "project": {"path_with_namespace": "g/r", "default_branch": "main"},
        "object_attributes": {"iid": 42, "action": "update"},
        "changes": {
            "labels": {
                "previous": [],
                "current": [{"title": "bug"}, {"title": "p1"}],
            }
        },
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert called == []
