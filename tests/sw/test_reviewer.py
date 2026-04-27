from pathlib import Path
from unittest.mock import MagicMock

from sw.reviewer import MUST_DIMENSIONS, ReviewResult, run_review_matrix


def _make_marker(repo_path: Path, dim: str, result: str, reason: str = ""):
    review_dir = repo_path / ".review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / f"{dim}.yaml").write_text(f"result: {result}\nreason: {reason}\n")


def test_review_matrix_all_pass(tmp_path: Path):
    """All 7 dimensions return PASS → all_passed=True."""
    cc = MagicMock()

    def fake_run(*, prompt, cwd, **kwargs):
        # The dimension is in the prompt; figure out which one and write marker
        for dim in MUST_DIMENSIONS:
            if dim in prompt:
                _make_marker(Path(cwd), dim, "PASS")
                break
        return MagicMock(returncode=0, stdout="", stderr="")

    cc.run.side_effect = fake_run

    result = run_review_matrix(
        mr_iid=1,
        project_path="g/r",
        claude=cc,
        repo_path=tmp_path,
    )

    assert isinstance(result, ReviewResult)
    assert result.all_passed is True
    assert result.failed_dimensions == []
    assert set(result.dimension_results.keys()) == set(MUST_DIMENSIONS)
    assert all(v == "PASS" for v in result.dimension_results.values())
    assert cc.run.call_count == len(MUST_DIMENSIONS)


def test_review_matrix_one_fail(tmp_path: Path):
    """One dimension FAIL → all_passed=False, failed_dimensions populated."""
    cc = MagicMock()

    def fake_run(*, prompt, cwd, **kwargs):
        for dim in MUST_DIMENSIONS:
            if dim in prompt:
                if dim == "security":
                    _make_marker(Path(cwd), dim, "FAIL", "SQL injection risk")
                else:
                    _make_marker(Path(cwd), dim, "PASS")
                break
        return MagicMock(returncode=0, stdout="", stderr="")

    cc.run.side_effect = fake_run

    result = run_review_matrix(
        mr_iid=1,
        project_path="g/r",
        claude=cc,
        repo_path=tmp_path,
    )

    assert result.all_passed is False
    assert "security" in result.failed_dimensions
    assert result.dimension_results["security"] == "FAIL"


def test_review_matrix_missing_marker_treated_as_fail(tmp_path: Path):
    """Subprocess returned 0 but no marker — treat as FAIL (fail-closed)."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    # NEVER write a marker

    result = run_review_matrix(
        mr_iid=1,
        project_path="g/r",
        claude=cc,
        repo_path=tmp_path,
    )

    assert result.all_passed is False
    assert len(result.failed_dimensions) == len(MUST_DIMENSIONS)


def test_review_matrix_subprocess_error_treated_as_fail(tmp_path: Path):
    """Subprocess returncode != 0 → treat as FAIL (fail-closed)."""
    cc = MagicMock()
    cc.run.return_value = MagicMock(returncode=1, stdout="", stderr="rate limit")

    result = run_review_matrix(
        mr_iid=1,
        project_path="g/r",
        claude=cc,
        repo_path=tmp_path,
    )

    assert result.all_passed is False
    assert len(result.failed_dimensions) == len(MUST_DIMENSIONS)


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
