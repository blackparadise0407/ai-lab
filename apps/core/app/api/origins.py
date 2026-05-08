import os

from dotenv import load_dotenv

DEFAULT_ALLOWED_BROWSER_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _parse_allowed_browser_origins(raw_origins: str | None) -> tuple[str, ...]:
    if not raw_origins:
        return DEFAULT_ALLOWED_BROWSER_ORIGINS

    parsed_origins = tuple(
        origin.strip().rstrip("/")
        for origin in raw_origins.split(",")
        if origin.strip()
    )
    return parsed_origins or DEFAULT_ALLOWED_BROWSER_ORIGINS


load_dotenv()
ALLOWED_BROWSER_ORIGINS = _parse_allowed_browser_origins(os.getenv("ALLOWED_BROWSER_ORIGINS"))


def is_allowed_browser_origin(origin: str | None) -> bool:
    return origin is not None and origin.rstrip("/") in ALLOWED_BROWSER_ORIGINS
