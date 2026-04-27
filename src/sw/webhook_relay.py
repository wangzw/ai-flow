import os

import gitlab
from flask import Flask, jsonify, request


def create_app() -> Flask:
    app = Flask(__name__)
    secret = os.environ["WEBHOOK_SECRET"]

    @app.post("/webhook")
    def webhook():
        if request.headers.get("X-Gitlab-Token") != secret:
            return jsonify({"error": "unauthorized"}), 401

        payload = request.get_json(silent=True) or {}
        kind = payload.get("object_kind")
        project_path = (payload.get("project") or {}).get("path_with_namespace")
        if not project_path:
            return jsonify({"ok": True, "ignored": "no project path"}), 200

        triggered = False

        if kind == "issue":
            triggered = _maybe_trigger_issue(payload, project_path)
        elif kind == "note":
            triggered = _maybe_trigger_note(payload, project_path)
        elif kind == "merge_request":
            triggered = _maybe_trigger_mr(payload, project_path)

        return jsonify({"ok": True, "triggered": triggered}), 200

    return app


def _maybe_trigger_issue(payload: dict, project_path: str) -> bool:
    changes = payload.get("changes", {})
    label_change = changes.get("labels")
    if not label_change:
        return False
    prev = {label["title"] for label in label_change.get("previous", [])}
    curr = {label["title"] for label in label_change.get("current", [])}
    added = curr - prev
    iid = payload["object_attributes"]["iid"]
    for label in added:
        _trigger_pipeline(
            project_path=project_path,
            ref=payload["project"].get("default_branch", "main"),
            variables={
                "CI_TRIGGERED_EVENT": "issue_label_added",
                "SW_ISSUE_IID": str(iid),
                "SW_LABEL_ADDED": label,
            },
        )
        return True
    return False


def _maybe_trigger_note(payload: dict, project_path: str) -> bool:
    obj = payload.get("object_attributes", {})
    if obj.get("noteable_type") != "Issue":
        return False
    issue = payload.get("issue") or {}
    _trigger_pipeline(
        project_path=project_path,
        ref=payload["project"].get("default_branch", "main"),
        variables={
            "CI_TRIGGERED_EVENT": "issue_note_added",
            "SW_ISSUE_IID": str(issue.get("iid")),
            "SW_COMMENT_BODY": obj.get("note", ""),
        },
    )
    return True


def _maybe_trigger_mr(payload: dict, project_path: str) -> bool:
    changes = payload.get("changes", {})
    draft = changes.get("draft") or changes.get("work_in_progress")
    if not draft:
        return False
    if not (draft.get("previous") is True and draft.get("current") is False):
        return False
    iid = payload["object_attributes"]["iid"]
    _trigger_pipeline(
        project_path=project_path,
        ref=payload["project"].get("default_branch", "main"),
        variables={
            "CI_TRIGGERED_EVENT": "mr_ready",
            "SW_MR_IID": str(iid),
        },
    )
    return True


def _trigger_pipeline(*, project_path: str, ref: str, variables: dict[str, str]) -> None:
    gl = gitlab.Gitlab(
        url=os.environ.get("CI_SERVER_URL", "https://gitlab.com"),
        private_token=os.environ["GITLAB_API_TOKEN"],
    )
    project = gl.projects.get(project_path)
    project.pipelines.create(
        {
            "ref": ref,
            "variables": [{"key": k, "value": v} for k, v in variables.items()],
        }
    )


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=8080)
