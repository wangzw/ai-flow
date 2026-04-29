"""Blast radius heuristic (spec §7.5).

Pure function. No LLM. Used to scale review max_iterations / MAY dimensions.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BlastRadiusInput:
    files_changed: list[str]
    lines_changed: int


def compute_blast_radius(
    inp: BlastRadiusInput,
    *,
    core_modules: list[str] | None = None,
    migration_globs: list[str] | None = None,
    public_api_globs: list[str] | None = None,
) -> str:
    """Return one of 'low' | 'medium' | 'high'."""
    core_modules = core_modules or []
    migration_globs = migration_globs or ["migrations/", ".sql"]
    public_api_globs = public_api_globs or ["api/", "/public/"]

    score = 0

    # Core modules (substring match for simplicity v1)
    if any(any(cm in f for cm in core_modules) for f in inp.files_changed):
        score += 3

    # Migrations
    if any(
        any(g in f for g in migration_globs) or f.endswith(".sql")
        for f in inp.files_changed
    ):
        score += 3

    # Lines changed
    if inp.lines_changed > 500:
        score += 2
    elif inp.lines_changed > 100:
        score += 1

    # Public API
    if any(any(g in f for g in public_api_globs) for f in inp.files_changed):
        score += 2

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"
