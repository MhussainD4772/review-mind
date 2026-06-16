import hashlib
import hmac
import logging
import os

from dotenv import load_dotenv
from fastapi import APIRouter, Header, HTTPException, Request

from app.db.session import SyncSessionLocal
from app.services.persistence import upsert_repository
from app.workers.tasks import (
    delta_index_repository_task,
    index_repository_task,
    review_pull_request,
)

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")


def verify_signature(payload: bytes, signature: str) -> bool:
    expected = (
        "sha256="
        + hmac.new(
            WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_hub_signature_256: str = Header(...),
):
    payload = await request.body()

    if not verify_signature(payload=payload, signature=x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event == "pull_request":
        data = await request.json()
        action = data.get("action")
        if action == "opened":
            pr = data["pull_request"]
            repo = data["repository"]
            logger.info(
                f"PR opened: #{pr['number']} '{pr['title']}' "
                f"in {repo['full_name']} by {pr['user']['login']}"
            )
            review_pull_request.delay(
                repo_full_name=repo["full_name"],
                pr_number=pr["number"],
                pr_title=pr["title"],
                github_repo_id=repo["id"],
                installation_id=data["installation"]["id"],
                pr_author=pr["user"]["login"],
            )

        if action == "closed" and data["pull_request"].get("merged"):
            pr = data["pull_request"]
            repo = data["repository"]
            installation_id = data["installation"]["id"]

            db = SyncSessionLocal()
            try:
                repository_id = upsert_repository(
                    db,
                    repo["id"],
                    repo["full_name"],
                    installation_id,
                )
            finally:
                db.close()

            logger.info(
                f"PR #{pr['number']} merged in {repo['full_name']}, delta-indexing"
            )
            delta_index_repository_task.delay(
                repo_full_name=repo["full_name"],
                pr_number=pr["number"],
                installation_id=installation_id,
                repository_id=repository_id,
            )

    if x_github_event == "installation":
        data = await request.json()
        action = data.get("action")
        if action == "created":
            installation_id = data["installation"]["id"]
            repositories = data.get("repositories", [])

            db = SyncSessionLocal()
            try:
                for repo in repositories:
                    repository_id = upsert_repository(
                        db,
                        repo["id"],
                        repo["full_name"],
                        installation_id,
                    )
                    logger.info(f"Installed on {repo['full_name']}, indexing queued")
                    index_repository_task.delay(
                        repo_full_name=repo["full_name"],
                        installation_id=installation_id,
                        repository_id=repository_id,
                    )
            finally:
                db.close()

    return {"status": "ok"}
