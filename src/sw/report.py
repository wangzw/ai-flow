"""CLI to compute aggregate statistics from a metrics log file."""

import json
import sys
from collections import Counter
from pathlib import Path


def _load_records(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def compute_report(path: Path) -> dict:
    records = _load_records(path)

    # Per-Issue tracking
    blocked_issues: set[int] = set()
    completed_issues: set[int] = set()

    for r in records:
        iid = r.get("issue_iid")
        ev = r.get("event")
        if ev == "coder_blocker" and iid is not None:
            blocked_issues.add(iid)
        if ev == "merged" and iid is not None:
            completed_issues.add(iid)

    automated = len(completed_issues - blocked_issues)
    completed = len(completed_issues)
    automation_rate = (automated / completed) if completed else 0.0

    blocker_histogram: Counter = Counter()
    for r in records:
        if r.get("event") == "coder_blocker":
            blocker_histogram[r.get("fields", {}).get("blocker_type", "unknown")] += 1

    return {
        "completed": completed,
        "automated": automated,
        "automation_rate": automation_rate,
        "blocker_histogram": dict(blocker_histogram),
    }


def format_report(report: dict) -> str:
    lines = [
        "=" * 50,
        "AI Coding Workflow — Aggregate Report",
        "=" * 50,
        f"Completed Issues: {report['completed']}",
        f"Fully automated:  {report['automated']}",
        f"Automation rate:  {report['automation_rate']:.1%}",
        "",
        "Blocker histogram:",
    ]
    for blocker, count in sorted(report["blocker_histogram"].items(), key=lambda x: -x[1]):
        lines.append(f"  {blocker}: {count}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m sw.report <metrics-file>", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    report = compute_report(path)
    print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
