from dataclasses import dataclass, field

MUST_DIMENSIONS = (
    "ac_compliance",
    "test_quality",
    "security",
    "performance",
    "consistency",
    "documentation_sync",
    "migration_safety",
)


@dataclass(frozen=True)
class ReviewResult:
    all_passed: bool
    dimension_results: dict[str, str]  # dimension -> "PASS" | "FAIL"
    failed_dimensions: list[str] = field(default_factory=list)


def run_review_matrix(*, mr_iid: int, project_path: str) -> ReviewResult:
    """Stub: always returns PASS for all MUST dimensions.

    Real implementation will dispatch to per-dimension Reviewer Agents.
    """
    dim_results = {dim: "PASS" for dim in MUST_DIMENSIONS}
    return ReviewResult(all_passed=True, dimension_results=dim_results, failed_dimensions=[])
