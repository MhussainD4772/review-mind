import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.url import normalize_async_database_url, normalize_sync_database_url

load_dotenv()

_RAW_DATABASE_URL = os.getenv("DATABASE_URL")
if not _RAW_DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

ASYNC_DATABASE_URL = normalize_async_database_url(_RAW_DATABASE_URL)
SYNC_DATABASE_URL = normalize_sync_database_url(_RAW_DATABASE_URL)

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

__all__ = ["Base", "AsyncSessionLocal", "SyncSessionLocal", "engine", "sync_engine"]
