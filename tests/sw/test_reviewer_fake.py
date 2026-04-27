from sw.reviewer_fake import ReviewResult, run_review_matrix


def test_stub_returns_all_pass():
    result = run_review_matrix(mr_iid=42, project_path="g/r")
    assert isinstance(result, ReviewResult)
    assert result.all_passed is True
    assert result.failed_dimensions == []


def test_stub_includes_all_must_dimensions():
    result = run_review_matrix(mr_iid=42, project_path="g/r")
    expected = {
        "ac_compliance",
        "test_quality",
        "security",
        "performance",
        "consistency",
        "documentation_sync",
        "migration_safety",
    }
    assert set(result.dimension_results.keys()) == expected
    for status in result.dimension_results.values():
        assert status == "PASS"
