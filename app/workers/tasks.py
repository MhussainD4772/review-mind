import logging

from app.services.review_service import fetch_pr_diff, generate_review
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="review_pull_request")
def review_pull_request(repo_full_name: str, pr_number: int, pr_title: str):
    logger.info(
        f"Worker picked up job: PR #{pr_number} '{pr_title}' in {repo_full_name}"
    )
    diff = fetch_pr_diff(repo_full_name, pr_number)
    if not diff:
        logger.warning(f"No diff found for PR #{pr_number}")
        return {"status": "skipped", "reason": "empty diff"}

    review = generate_review(diff, pr_title)
    logger.info(f"Review generated for PR #{pr_number}:\n{review}")

    return {"status": "completed", "pr_number": pr_number}
