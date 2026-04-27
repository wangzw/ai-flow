from pathlib import Path
from unittest.mock import MagicMock

from sw.reviewer import MUST_DIMENSIONS, ReviewResult, run_review_matrix


def _make_per_dim_marker(repo_path: Path, dim: str, result: str, reason: str = ""):
    review_dir = repo_path / ".review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / f"{dim}.yaml").write_text(f"result: {result}\nreason: {reason}\n")


def _make_combined_marker(repo_path: Path, results: dict[str, str], reasons: dict[str, str] | None = None):
    review_dir = repo_path / ".review"
    review_dir.mkdir(exist_ok=True)
    lines = ["results:"]
    for dim, status in results.items():
        lines.append(f"  {dim}: {status}")
    lines.append("reasons:")
    for dim in results:
        r = (reasons or {}).get(dim, "")
        lines.append(f"  {dim}: {r}")
    (review_dir / "combined.yaml").write_text("\n".join(lines) + "\n")


# === Combined mode (default) tests ===


def test_combined_all_pass(tmp_path: Path):
    """All 7 dimensions PASS via combined marker → all_passed=True; only 1 CLI call."""
    cc = MagicMock()

    def fake_run(*, prompt, cwd, **kwargs):
        _make_combined_marker(Path(cwd), {dim: "PASS" for dim in MUST_DIMENSIONS})
        return MagicMock(returncode=0, stdout="", stderr="")

    cc.run.side_effect = fake_run
    result = run_review_matrix(mr_iid=1, project_path="g/r", claude=cc, repo_path=tmp_path)

    assert result.all_passed is True
    assert result.failed_dimensions == []
    assert all(v == "PASS" for v in result.dimension_results.values())
    assert cc.run.call_count == 1  # combined mode = single call


def test_combined_one_fail(tmp_path: Path):
    cc = MagicMock()

    def fake_run(*, prompt, cwd, **kwargs):
        results = {dim: ("FAIL" if dim == "security" else "PASS") for dim in MUST_DIMENSIONS}
        reasons = {"security": "SQL injection"}
        _make_combined_marker(Path(cwd), results, reasons)
        return MagicMock(returncode=0, stdout="", stderr="")

    cc.run.side_effect = fake_run
    result = run_review_matrix(mr_iid=1, project_path="g/r", claude=cc, repo_path=tmp_path)

    assert result.all_passed is False
    assert "security" in result.failed_dimensions
    assert result.dimension_results["security"] == "FAIL"
    assert "SQL injection" in result.reasons["security"]


def test_combined_no_marker_fail_closed(tmp_path: Path):
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    # No marker written

    result = run_review_matrix(mr_iid=1, project_path="g/r", claude=cc, repo_path=tmp_path)

    assert result.all_passed is False
    assert len(result.failed_dimensions) == len(MUST_DIMENSIONS)


def test_combined_subprocess_error_fail_closed(tmp_path: Path):
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=1, stdout="", stderr="rate limit")

    result = run_review_matrix(mr_iid=1, project_path="g/r", claude=cc, repo_path=tmp_path)

    assert result.all_passed is False
    assert len(result.failed_dimensions) == len(MUST_DIMENSIONS)


# === Legacy per-dim mode (combined=False) tests ===


def test_per_dim_all_pass(tmp_path: Path):
    """combined=False: 7 separate CLI calls, one marker per dim."""
    cc = MagicMock()

    def fake_run(*, prompt, cwd, **kwargs):
        for dim in MUST_DIMENSIONS:
            if dim in prompt:
                _make_per_dim_marker(Path(cwd), dim, "PASS")
                break
        return MagicMock(returncode=0, stdout="", stderr="")

    cc.run.side_effect = fake_run
    result = run_review_matrix(
        mr_iid=1, project_path="g/r", claude=cc, repo_path=tmp_path, combined=False
    )

    assert isinstance(result, ReviewResult)
    assert result.all_passed is True
    assert cc.run.call_count == len(MUST_DIMENSIONS)


def test_per_dim_one_fail(tmp_path: Path):
    cc = MagicMock()

    def fake_run(*, prompt, cwd, **kwargs):
        for dim in MUST_DIMENSIONS:
            if dim in prompt:
                if dim == "security":
                    _make_per_dim_marker(Path(cwd), dim, "FAIL", "SQL injection")
                else:
                    _make_per_dim_marker(Path(cwd), dim, "PASS")
                break
        return MagicMock(returncode=0, stdout="", stderr="")

    cc.run.side_effect = fake_run
    result = run_review_matrix(
        mr_iid=1, project_path="g/r", claude=cc, repo_path=tmp_path, combined=False
    )

    assert result.all_passed is False
    assert "security" in result.failed_dimensions


def test_must_dimensions_list_matches_spec():
    expected = {
        "ac_compliance",
        "test_quality",
        "security",
        "performance",
        "consistency",
        "documentation_sync",
        "migration_safety",
    }
    assert set(MUST_DIMENSIONS) == expected
