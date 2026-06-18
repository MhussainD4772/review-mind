import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

_RAW_DATABASE_URL = os.getenv("DATABASE_URL")
if not _RAW_DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# Normalize to handle postgres://, postgresql://, postgresql+asyncpg://,
# and postgresql+psycopg2:// so we control both driver forms explicitly.
_parts = _RAW_DATABASE_URL.split("://", 1)
if len(_parts) != 2:
    raise RuntimeError(f"Malformed DATABASE_URL: {_RAW_DATABASE_URL!r}")

_scheme, _rest = _parts
_scheme = _scheme.split("+", 1)[0]  # postgresql+asyncpg -> postgresql
if _scheme == "postgres":
    _scheme = "postgresql"  # SQLAlchemy rejects the bare "postgres" scheme

ASYNC_DATABASE_URL = f"{_scheme}+asyncpg://{_rest}"
SYNC_DATABASE_URL = f"{_scheme}+psycopg2://{_rest}"

# --- Async: for FastAPI request handlers ---
engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# --- Sync: for Celery workers ---
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass
