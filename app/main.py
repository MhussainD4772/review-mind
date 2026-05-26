from fastapi import FastAPI
from app.api.webhooks import router as webhook_router
import logging


app = FastAPI(
    title="ReviewMind API",
    description="AI-powered code review for Github pull requests",
    version="0.1.0",
)

app.include_router(webhook_router)
logging.basicConfig(level=logging.INFO)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "reviewmind-api"}


