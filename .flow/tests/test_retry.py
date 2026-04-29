from flow.retry import classify_blocker, compute_next_attempt, is_due


def test_classify_5xx():
    assert classify_blocker("", "503 Service Unavailable", 1) == "model_5xx"


def test_classify_rate_limit():
    assert classify_blocker("rate limit exceeded", "", 1) == "rate_limit"
    assert classify_blocker("", "HTTP 429 too many requests", 1) == "rate_limit"


def test_classify_oom():
    assert classify_blocker("", "Killed: out of memory", 137) == "sandbox_oom"


def test_classify_default_tool_error():
    assert classify_blocker("", "weird unknown failure", 1) == "tool_error"


def test_compute_next_attempt_schedules():
    cfg = {"tool_error": {"max_attempts": 3, "backoff": [60, 120]}}
    nxt, state = compute_next_attempt(category="tool_error", attempt=0, retry_config=cfg)
    assert nxt is not None
    assert state["attempts"] == 1
    assert not state["exhausted"]


def test_compute_next_attempt_exhausted():
    cfg = {"quota": {"max_attempts": 0}}
    nxt, state = compute_next_attempt(category="quota", attempt=0, retry_config=cfg)
    assert nxt is None
    assert state["exhausted"]


def test_is_due_false_when_no_state():
    assert is_due(None) is False
    assert is_due({}) is False
