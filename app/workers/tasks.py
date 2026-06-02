import logging

from app.db.session import SyncSessionLocal
from app.services.persistence import (
    complete_review,
    create_review,
    fail_review,
    upsert_pull_request,
    upsert_repository,
)
from app.services.review_service import (
    fetch_pr_diff,
    generate_review,
    post_review_comment,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="review_pull_request")
def review_pull_request(
    repo_full_name: str,
    pr_number: int,
    pr_title: str,
    github_repo_id: int,
    installation_id: int,
    pr_author: str,
):
    logger.info(
        f"Worker picked up job: PR #{pr_number} '{pr_title}' in {repo_full_name}"
    )

    db = SyncSessionLocal()
    review_id = None
    try:
        repo_id = upsert_repository(db, github_repo_id, repo_full_name, installation_id)
        pr_id = upsert_pull_request(
            db,
            repo_id,
            pr_number,
            pr_title,
            pr_author,
        )
        review_id = create_review(db, pr_id)

        diff = fetch_pr_diff(repo_full_name, pr_number)
        if not diff:
            logger.warning(f"No diff found for PR #{pr_number}")
            fail_review(db, review_id)
            return {"status": "skipped", "reason": "empty diff"}

        review = generate_review(diff, pr_title)
        post_review_comment(repo_full_name, pr_number, review)
        complete_review(db, review_id, review)

        logger.info(f"Review posted to PR #{pr_number}")
        return {"status": "completed", "pr_number": pr_number}

    except Exception:

        logger.exception(f"Review failed for PR #{pr_number}")

        if review_id is not None:
            fail_review(db, review_id)
        raise
    finally:
        db.close()
