ALLOWED_BROWSER_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def is_allowed_browser_origin(origin: str | None) -> bool:
    return origin in ALLOWED_BROWSER_ORIGINS
