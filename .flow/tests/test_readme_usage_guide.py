from pathlib import Path


README = Path(__file__).resolve().parents[2] / "README.md"


def test_readme_includes_external_adoption_flow():
    content = README.read_text()

    assert "## Adopt ai-flow in another repository" in content
    assert 'flow init' in content
    assert 'flow apply-labels --repo <owner/repo>' in content
    assert 'flow doctor --repo <owner/repo>' in content
    assert '.github/ISSUE_TEMPLATE/goal.md' in content
    assert '`agent-ready` label' in content


def test_readme_lists_workflow_runtime_prerequisites():
    content = README.read_text()

    assert 'pip install -e ./.flow' in content
    assert 'npm install -g @github/copilot' in content
    assert 'secrets.COPILOT_GITHUB_TOKEN' in content
    assert 'secrets.ACTION_GITHUB_TOKEN' in content
    assert 'secrets.GITHUB_TOKEN' in content
    assert '.flow/pyproject.toml' in content
    assert '.flow/src' in content
