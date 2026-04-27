"""Smoke tests for github_dispatch CLI parsing.

The command bodies are platform-specific and tested at integration level.
Here we just verify the entry point routes commands correctly.
"""



from sw import github_dispatch


def test_unknown_command_exits_2(capsys):
    rc = github_dispatch.main(["bogus"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "usage" in captured.err.lower()


def test_no_command_exits_2(capsys):
    rc = github_dispatch.main([])
    assert rc == 2


def test_known_commands_routed(monkeypatch):
    """Each declared command resolves to a callable."""
    expected = {"issue-labeled", "comment-created", "pr-ready", "merge-queue"}
    assert set(github_dispatch._COMMANDS.keys()) == expected
    for name, fn in github_dispatch._COMMANDS.items():
        assert callable(fn), f"{name} not callable"
