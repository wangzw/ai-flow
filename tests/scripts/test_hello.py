"""Test module for scripts.hello module."""

from scripts.hello import hello


def test_hello():
    """Test that hello() returns the expected greeting."""
    assert hello() == "hello, world"