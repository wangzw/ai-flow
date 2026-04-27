import json
from pathlib import Path

from sw.metrics import EVENTS, emit


def test_emit_writes_json_line_to_stdout(capsys, monkeypatch):
    monkeypatch.delenv("SW_METRICS_FILE", raising=False)
    emit("ac_validation", issue_iid=42, result="PASS")
    out = capsys.readouterr().out.strip()
    assert out.startswith("{")
    record = json.loads(out)
    assert record["event"] == "ac_validation"
    assert record["issue_iid"] == 42
    assert record["fields"]["result"] == "PASS"
    assert "ts" in record


def test_emit_appends_to_file_when_env_set(tmp_path: Path, monkeypatch):
    log = tmp_path / "metrics.log"
    monkeypatch.setenv("SW_METRICS_FILE", str(log))
    emit("ac_validation", issue_iid=42, result="PASS")
    emit("coder_dispatched", issue_iid=42)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "ac_validation"
    assert json.loads(lines[1])["event"] == "coder_dispatched"


def test_emit_swallows_io_errors(monkeypatch, capsys):
    """Metrics emission must not break the workflow."""
    monkeypatch.setenv("SW_METRICS_FILE", "/nonexistent/dir/log")  # writable=False
    # Should NOT raise
    emit("ac_validation", issue_iid=42, result="PASS")


def test_events_constant_provides_known_names():
    assert EVENTS.AC_VALIDATION == "ac_validation"
    assert EVENTS.CODER_DISPATCHED == "coder_dispatched"
    assert EVENTS.CODER_BLOCKER == "coder_blocker"
    assert EVENTS.REVIEWER_PASSED == "reviewer_passed"
    assert EVENTS.REVIEWER_FAILED == "reviewer_failed"
    assert EVENTS.ENQUEUED == "enqueued"
    assert EVENTS.MERGED == "merged"
    assert EVENTS.DEQUEUED == "dequeued"
    assert EVENTS.COMMAND_RECEIVED == "command_received"
    assert EVENTS.QUEUE_POP == "queue_pop"


def test_emit_without_issue_iid_omits_or_nulls_field(monkeypatch, capsys):
    monkeypatch.delenv("SW_METRICS_FILE", raising=False)
    emit("merged")
    record = json.loads(capsys.readouterr().out.strip())
    assert record.get("issue_iid") is None
