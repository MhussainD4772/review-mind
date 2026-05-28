import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="review_pull_request")
def review_pull_request(repo_full_name: str, pr_number: int, pr_title: str):
    logger.info(
        f"Worker picked up job: PR #{pr_number} '{pr_title}' in {repo_full_name}"
    )
    # Phase 4: fetch diff, call Gemini, post review
    return {"status": "received", "pr_number": pr_number}
