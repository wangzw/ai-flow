from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from flow.cli import main


def test_init_bootstraps_runtime_and_workflows(tmp_path: Path):
    runner = CliRunner()
    target = tmp_path / "target-repo"

    result = runner.invoke(main, ["init", "--target", str(target)])

    assert result.exit_code == 0, result.output
    for rel_path in (
        ".flow/pyproject.toml",
        ".flow/src/flow/cli.py",
        ".flow/src/flow/coordinator.py",
        ".flow/config.yml",
        ".github/workflows/flow-issue.yml",
        ".github/ISSUE_TEMPLATE/goal.md",
    ):
        assert (target / rel_path).exists(), rel_path
    assert "flow apply-labels --repo <owner/repo>" in result.output
    assert "flow doctor --repo <owner/repo>" in result.output
