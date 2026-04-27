import json
from pathlib import Path

from sw.report import compute_report, format_report, main


def _write_metrics(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_automation_rate_basic(tmp_path: Path):
    log = tmp_path / "m.log"
    _write_metrics(log, [
        # Issue 1: completed without needs-human → automated
        {"event": "ac_validation", "issue_iid": 1, "fields": {"result": "PASS"}},
        {"event": "merged", "issue_iid": 1, "fields": {}},
        # Issue 2: hit needs-human → not fully automated
        {"event": "ac_validation", "issue_iid": 2, "fields": {"result": "PASS"}},
        {"event": "coder_blocker", "issue_iid": 2, "fields": {"blocker_type": "ac_ambiguity"}},
        {"event": "merged", "issue_iid": 2, "fields": {}},
        # Issue 3: not yet merged
        {"event": "ac_validation", "issue_iid": 3, "fields": {"result": "PASS"}},
    ])
    rep = compute_report(log)
    assert rep["completed"] == 2
    assert rep["automated"] == 1
    assert rep["automation_rate"] == 0.5


def test_blocker_histogram(tmp_path: Path):
    log = tmp_path / "m.log"
    _write_metrics(log, [
        {"event": "coder_blocker", "issue_iid": 1, "fields": {"blocker_type": "ac_ambiguity"}},
        {"event": "coder_blocker", "issue_iid": 2, "fields": {"blocker_type": "ac_ambiguity"}},
        {"event": "coder_blocker", "issue_iid": 3, "fields": {"blocker_type": "conflict"}},
    ])
    rep = compute_report(log)
    assert rep["blocker_histogram"]["ac_ambiguity"] == 2
    assert rep["blocker_histogram"]["conflict"] == 1


def test_format_report_includes_key_metrics(tmp_path: Path):
    log = tmp_path / "m.log"
    _write_metrics(log, [
        {"event": "merged", "issue_iid": 1, "fields": {}},
    ])
    rep = compute_report(log)
    text = format_report(rep)
    assert "Automation rate" in text or "automation" in text.lower()
    assert "1" in text


def test_main_cli_prints_to_stdout(tmp_path: Path, capsys):
    log = tmp_path / "m.log"
    _write_metrics(log, [{"event": "merged", "issue_iid": 1, "fields": {}}])
    rc = main([str(log)])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_main_missing_arg_prints_usage(capsys):
    rc = main([])
    assert rc == 2
    assert "usage" in capsys.readouterr().err.lower()
