import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.webhooks import router as webhook_router
from app.db.migrate import run_migrations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(
    title="ReviewMind API",
    description="AI-powered code review for Github pull requests",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)
logging.basicConfig(level=logging.INFO)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "reviewmind-api"}
