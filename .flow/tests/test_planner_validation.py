"""Tests for strict Planner result.yaml validation (spec §5.4)."""

from flow.planner import _build_retry_feedback, validate_planner_marker


def test_valid_ok_marker_passes():
    marker = {
        "schema_version": 1,
        "status": "ok",
        "desired_plan": [
            {
                "task_id": "T-readme-usage-guide",
                "spec": {
                    "goal": "Add usage guide to README",
                    "quality_criteria": [
                        "README has Use ai-flow section",
                    ],
                },
                "deps": [],
            }
        ],
    }
    assert validate_planner_marker(marker) == []


def test_valid_done_marker_passes():
    marker = {
        "schema_version": 1,
        "status": "done",
        "summary": "All tasks completed; goal accomplished.",
    }
    assert validate_planner_marker(marker) == []


def test_valid_blocked_marker_passes():
    marker = {
        "schema_version": 1,
        "status": "blocked",
        "blocker": {"question": "Should we keep flow init or remove it?"},
    }
    assert validate_planner_marker(marker) == []


def test_non_dict_top_level_rejected():
    errors = validate_planner_marker(["not", "a", "dict"])
    assert errors and "mapping" in errors[0]


def test_unknown_status_rejected():
    errors = validate_planner_marker({"schema_version": 1, "status": "weird"})
    assert any("status" in e and "weird" in e for e in errors)


def test_missing_schema_version_rejected():
    errors = validate_planner_marker({"status": "done", "summary": "x"})
    assert any("schema_version" in e for e in errors)


def test_ok_with_empty_desired_plan_rejected():
    marker = {"schema_version": 1, "status": "ok", "desired_plan": []}
    errors = validate_planner_marker(marker)
    assert any("desired_plan" in e and "empty" in e for e in errors)


def test_ok_task_missing_id_rejected():
    marker = {
        "schema_version": 1,
        "status": "ok",
        "desired_plan": [{"task_id": "", "spec": {"goal": "g",
                                                  "quality_criteria": ["c"]}}],
    }
    errors = validate_planner_marker(marker)
    assert any("task_id" in e for e in errors)


def test_ok_task_id_bad_format_rejected():
    marker = {
        "schema_version": 1,
        "status": "ok",
        "desired_plan": [
            {
                "task_id": "readme_usage",  # missing T- prefix, has underscore
                "spec": {"goal": "g", "quality_criteria": ["c"]},
            }
        ],
    }
    errors = validate_planner_marker(marker)
    assert any("kebab" in e or "T-" in e for e in errors)


def test_ok_duplicate_task_ids_rejected():
    marker = {
        "schema_version": 1,
        "status": "ok",
        "desired_plan": [
            {"task_id": "T-a", "spec": {"goal": "g", "quality_criteria": ["c"]}},
            {"task_id": "T-a", "spec": {"goal": "g", "quality_criteria": ["c"]}},
        ],
    }
    errors = validate_planner_marker(marker)
    assert any("duplicated" in e for e in errors)


def test_ok_task_missing_spec_fields_rejected():
    marker = {
        "schema_version": 1,
        "status": "ok",
        "desired_plan": [
            {"task_id": "T-x", "spec": {"goal": "", "quality_criteria": []}}
        ],
    }
    errors = validate_planner_marker(marker)
    assert any("spec.goal" in e for e in errors)
    assert any("quality_criteria" in e for e in errors)


def test_done_without_summary_rejected():
    errors = validate_planner_marker({"schema_version": 1, "status": "done"})
    assert any("summary" in e for e in errors)


def test_blocked_without_question_rejected():
    errors = validate_planner_marker(
        {"schema_version": 1, "status": "blocked", "blocker": {}}
    )
    assert any("question" in e for e in errors)


def test_actions_modify_specs_must_be_list():
    marker = {
        "schema_version": 1,
        "status": "ok",
        "desired_plan": [
            {"task_id": "T-a", "spec": {"goal": "g", "quality_criteria": ["c"]}}
        ],
        "actions": {"modify_specs": "not a list"},
    }
    errors = validate_planner_marker(marker)
    assert any("modify_specs" in e and "list" in e for e in errors)


def test_retry_feedback_includes_errors_and_prior_marker():
    fb = _build_retry_feedback(
        attempt=2,
        reason="schema check failed",
        errors=["task_id missing", "summary empty"],
        marker={"status": "weird"},
    )
    assert "retry attempt #2" in fb
    assert "task_id missing" in fb
    assert "summary empty" in fb
    assert "weird" in fb  # prior marker is rendered


def test_retry_feedback_no_marker_case():
    fb = _build_retry_feedback(
        attempt=2,
        reason="result.yaml was not written",
        errors=["did not write file"],
        marker=None,
    )
    assert "no result.yaml was written" in fb


def test_run_planner_retries_on_invalid_marker(tmp_path, monkeypatch):
    """run_planner retries with feedback prompt when validation fails."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from flow.clients.fake import FakeAgentClient
    from flow.planner import run_planner

    monkeypatch.setattr("flow.planner._clone_repo",
                        lambda url, to_path, branch=None: (Path(to_path).mkdir(parents=True),
                                                           None)[1])
    monkeypatch.setenv("FLOW_PLANNER_MAX_ATTEMPTS", "3")

    call_count = {"n": 0}

    def write_marker(cwd: Path) -> None:
        call_count["n"] += 1
        marker_path = cwd / ".flow" / "result.yaml"
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        if call_count["n"] == 1:
            # First attempt: missing task_id
            marker_path.write_text(
                "schema_version: 1\nstatus: ok\n"
                "desired_plan:\n"
                "  - task_id: ''\n"
                "    spec: {goal: x, quality_criteria: [c]}\n"
            )
        elif call_count["n"] == 2:
            # Second attempt: bad task_id format
            marker_path.write_text(
                "schema_version: 1\nstatus: ok\n"
                "desired_plan:\n"
                "  - task_id: bad_format\n"
                "    spec: {goal: x, quality_criteria: [c]}\n"
            )
        else:
            # Third attempt: valid
            marker_path.write_text(
                "schema_version: 1\nstatus: ok\n"
                "desired_plan:\n"
                "  - task_id: T-good-task\n"
                "    spec: {goal: do thing, quality_criteria: [criterion one]}\n"
            )

    client = FakeAgentClient(on_run=write_marker)

    repo = MagicMock()
    repo.clone_url = "https://example.com/x.git"

    workdir = tmp_path / "wd"
    result = run_planner(
        repo=repo, goal_issue_number=42, input_bundle={"x": 1},
        base_branch="main", client=client, workdir=workdir,
    )

    assert result.status == "ok"
    assert call_count["n"] == 3
    assert len(client.calls) == 3
    # The 2nd & 3rd prompts must include retry-feedback markers
    assert "retry attempt #2" in client.calls[1]["prompt"]
    assert "retry attempt #3" in client.calls[2]["prompt"]
    # And include the prior errors
    assert "task_id" in client.calls[1]["prompt"]


def test_run_planner_gives_up_after_max_attempts(tmp_path, monkeypatch):
    from pathlib import Path
    from unittest.mock import MagicMock

    from flow.clients.fake import FakeAgentClient
    from flow.planner import run_planner

    monkeypatch.setattr("flow.planner._clone_repo",
                        lambda url, to_path, branch=None: (Path(to_path).mkdir(parents=True),
                                                           None)[1])
    monkeypatch.setenv("FLOW_PLANNER_MAX_ATTEMPTS", "2")

    def write_bad(cwd: Path) -> None:
        p = cwd / ".flow" / "result.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("schema_version: 1\nstatus: bogus\n")

    client = FakeAgentClient(on_run=write_bad)

    repo = MagicMock()
    repo.clone_url = "https://example.com/x.git"

    result = run_planner(
        repo=repo, goal_issue_number=1, input_bundle={},
        base_branch="main", client=client, workdir=tmp_path / "wd",
    )

    assert result.status == "no_marker"
    assert result.blocker["blocker_type"] == "invalid_marker"
    assert result.blocker["attempts"] == 2
    assert any("status" in e for e in result.blocker["errors"])
    assert len(client.calls) == 2
