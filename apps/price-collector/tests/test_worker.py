from app.worker import worker


def test_call_returns_json_error_instead_of_raising():
    def boom():
        raise RuntimeError("No module named 'playwright'")

    result = worker.call(boom, timeout=5)
    assert result["ok"] is False
    assert "playwright" in result["error"]
