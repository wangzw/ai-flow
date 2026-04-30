import re
from pathlib import Path

README_PATH = Path(__file__).resolve().parents[2] / "README.md"


def _section(body: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\n(?P<section>.*?)(?=^## |\Z)"
    match = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    assert match, f"missing README section: {heading}"
    return match.group("section")


def test_readme_documents_repository_adoption_flow():
    section = _section(README_PATH.read_text(), "Using ai-flow in another repository")

    for command in (
        "pip install -e ./.flow",
        "flow init",
        "flow apply-labels --repo <owner/repo>",
        "flow doctor --repo <owner/repo>",
    ):
        assert command in section

    assert "`flow init` bootstraps `.flow/`, `.github/workflows/`, and" in section
    assert "`.github/ISSUE_TEMPLATE/goal.md` into the target repository" in section
    assert "configure `.flow/config.yml`" in section
    assert "create a `type:goal` issue and label it" in section
    assert "`agent-ready`" in section
