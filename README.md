# ReviewMind

AI-powered code review for GitHub pull requests. ReviewMind reviews your PRs like a senior engineer who cares about your growth — explaining not just what to change, but why.

## Tech Stack

- **Backend:** FastAPI (Python 3.12)
- **Job Queue:** Redis + Celery
- **Database:** PostgreSQL + pgvector
- **AI:** Gemini API (config-swappable)
- **Frontend:** React (Vite)
- **Infra:** Docker, Docker Compose
- **Deployment:** Railway

## Project Structure
app/      FastAPI backend (api, services, workers, models)
web/      React frontend (Vite)
infra/    Docker & Docker Compose
.github/  CI workflows

## Running Locally

You need Docker Desktop installed and running.

```bash
# 1. Clone the repo
git clone https://github.com/MhussainD4772/review-mind.git
cd review-mind

# 2. Set up environment variables
cp .env.example .env

# 3. Start everything
docker compose -f infra/docker-compose.yml up --build
```

That's it. The following services will be available:

- Backend API: http://localhost:8000
- API Docs (Swagger): http://localhost:8000/docs
- Frontend: http://localhost:5173

To stop:

```bash
docker compose -f infra/docker-compose.yml down
```

## Development

Format and lint Python code before committing:

```bash
isort app/
black app/
flake8 app/
```

## License

MIT