from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def _normalized_readme() -> str:
    return " ".join(README.read_text().split())


def test_readme_includes_self_contained_adoption_commands():
    content = README.read_text()

    assert "## Use ai-flow in another repository" in content
    assert "pip install -e ./.flow" in content
    assert "flow init --target /path/to/your-repo" in content
    assert 'flow apply-labels --repo <owner/repo>' in content
    assert 'flow doctor --repo <owner/repo>' in content


def test_readme_explains_generated_files_configuration_and_first_goal():
    content = _normalized_readme()

    assert (
        "creates the target repository's `.flow/` runtime and `.github/` "
        "workflow/template files" in content
    )
    assert "edit `.flow/config.yml`" in content
    assert "`authorized_users`" in content
    assert "`blast_radius.core_modules`" in content
    assert "commit the generated `.flow/` and `.github/` files" in content
    assert "create the first `type:goal` issue with the `agent-ready` label" in content
