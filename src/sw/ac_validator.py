import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str = ""


_AC_BLOCK_RE = re.compile(
    r"<!--\s*ac:start\s*-->(.*?)<!--\s*ac:end\s*-->",
    re.DOTALL,
)
_AC_START_RE = re.compile(r"<!--\s*ac:start\s*-->")
_AC_END_RE = re.compile(r"<!--\s*ac:end\s*-->")


def validate_ac(issue_body: str) -> ValidationResult:
    """Validate that the Issue body contains a non-empty AC block."""
    has_start = bool(_AC_START_RE.search(issue_body))
    has_end = bool(_AC_END_RE.search(issue_body))

    if not has_start:
        return ValidationResult(valid=False, reason="Missing <!-- ac:start --> marker")
    if not has_end:
        return ValidationResult(valid=False, reason="Unclosed AC block: <!-- ac:end --> not found")

    match = _AC_BLOCK_RE.search(issue_body)
    if match is None:
        return ValidationResult(
            valid=False, reason="AC block markers found but not paired correctly"
        )

    content = match.group(1).strip()
    if not content:
        return ValidationResult(valid=False, reason="AC block is empty")

    return ValidationResult(valid=True)
