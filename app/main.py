
from fastapi import FastAPI

app = FastAPI(
    title="ReviewMind API",
    description="AI-powered code review for Github pull requests",
    version="0.1.0",
)

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "reviewmind-api"}

