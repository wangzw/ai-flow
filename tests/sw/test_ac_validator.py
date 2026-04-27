from sw.ac_validator import validate_ac


def test_valid_ac_block():
    body = """## 原始诉求
Add /api/users pagination.

## AC
<!-- ac:start -->
Given a user lists endpoint
When called with page=2 size=10
Then response includes items 11-20
<!-- ac:end -->
"""
    result = validate_ac(body)
    assert result.valid is True


def test_missing_ac_block():
    body = "## 原始诉求\nDo something."
    result = validate_ac(body)
    assert result.valid is False
    assert "ac:start" in result.reason.lower() or "missing" in result.reason.lower()


def test_empty_ac_block():
    body = """## AC
<!-- ac:start -->

<!-- ac:end -->
"""
    result = validate_ac(body)
    assert result.valid is False
    assert "empty" in result.reason.lower()


def test_unclosed_ac_block():
    body = """## AC
<!-- ac:start -->
something
"""
    result = validate_ac(body)
    assert result.valid is False
    assert "ac:end" in result.reason.lower() or "unclosed" in result.reason.lower()


def test_ac_with_only_whitespace_is_empty():
    body = """<!-- ac:start -->


<!-- ac:end -->"""
    result = validate_ac(body)
    assert result.valid is False
