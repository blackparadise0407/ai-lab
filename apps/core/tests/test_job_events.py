from __future__ import annotations

from app.api.origins import is_allowed_browser_origin


def test_allows_configured_browser_origins() -> None:
    assert is_allowed_browser_origin("http://localhost:5173")
    assert is_allowed_browser_origin("http://127.0.0.1:5173")


def test_rejects_untrusted_browser_origin() -> None:
    assert not is_allowed_browser_origin("https://malicious.example")


def test_rejects_missing_origin() -> None:
    assert not is_allowed_browser_origin(None)
