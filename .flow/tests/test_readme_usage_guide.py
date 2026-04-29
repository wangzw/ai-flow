from pathlib import Path


README = Path(__file__).resolve().parents[2] / "README.md"


def test_readme_includes_external_adoption_flow():
    content = README.read_text()

    assert "## Adopt ai-flow in another repository" in content
    assert 'python -m pip install "ai-flow @ git+https://github.com/wangzw/ai-flow.git#subdirectory=.flow"' in content
    assert 'flow init' in content
    assert 'flow apply-labels --repo <owner/repo>' in content
    assert 'flow doctor --repo <owner/repo>' in content
    assert 'git checkout ai-flow-upstream/main -- .flow/pyproject.toml .flow/src' in content
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
    assert 'actions/setup-python@v5' in content
    assert 'actions/setup-node@v4' in content


def test_readme_explains_how_to_start_ai_flow_after_setup():
    content = README.read_text()

    assert 'Open a new issue from `.github/ISSUE_TEMPLATE/goal.md`' in content
    assert 'It pre-labels the issue with `type:goal`.' in content
    assert 'Add the `agent-ready` label to that goal issue.' in content
    assert '`flow-issue.yml` listens for the `agent-ready` label' in content
