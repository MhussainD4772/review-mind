import os


def normalize_sync_database_url(raw: str) -> str:
    """Return a psycopg2 SQLAlchemy URL from any common Postgres URL form."""
    parts = raw.split("://", 1)
    if len(parts) != 2:
        raise RuntimeError(f"Malformed DATABASE_URL: {raw!r}")

    scheme, rest = parts
    scheme = scheme.split("+", 1)[0]
    if scheme == "postgres":
        scheme = "postgresql"

    return f"{scheme}+psycopg2://{rest}"


def normalize_async_database_url(raw: str) -> str:
    """Return an asyncpg SQLAlchemy URL from any common Postgres URL form."""
    parts = raw.split("://", 1)
    if len(parts) != 2:
        raise RuntimeError(f"Malformed DATABASE_URL: {raw!r}")

    scheme, rest = parts
    scheme = scheme.split("+", 1)[0]
    if scheme == "postgres":
        scheme = "postgresql"

    return f"{scheme}+asyncpg://{rest}"


def get_database_url() -> str:
    """Resolve the sync DB URL from DATABASE_URL."""
    raw = os.getenv("DATABASE_URL")
    if not raw:
        return ""
    return normalize_sync_database_url(raw)
