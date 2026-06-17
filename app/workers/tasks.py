import logging
import os

import redis
from google.api_core.exceptions import ResourceExhausted

from app.db.session import SyncSessionLocal
from app.services.indexing import (
    index_changed_files,
    index_repository,
    retrieve_relevant_chunks,
    retrieve_symbol_definitions,
)
from app.services.persistence import (
    complete_review,
    create_review,
    fail_review,
    repository_chunk_count,
    upsert_pull_request,
    upsert_repository,
)
from app.services.review_service import (
    fetch_pr_changed_files,
    fetch_pr_diff,
    generate_review,
    post_placeholder_comment,
    update_comment,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.Redis.from_url(REDIS_URL)

# Only one repository may be indexed at a time across the worker pool. Indexing
# is embedding-heavy and the API is quota-limited, so running many indexes at
# once (e.g. installing on many repos together) would burn the daily quota and
# trigger a storm of rate-limit errors. A shared lock serializes them; tasks
# that can't get the lock retry shortly instead of running concurrently.
INDEX_LOCK_KEY = "reviewmind:index_lock"
INDEX_LOCK_TIMEOUT = 60 * 60
INDEX_LOCK_RETRY_COUNTDOWN = 30
INDEX_LOCK_MAX_RETRIES = 120


def merge_chunks(*chunk_lists) -> list:
    """Combine chunk lists, dropping duplicates by file path and line span.

    Symbol-definition lookups and semantic retrieval frequently surface the
    same chunk; we want each piece of context in the prompt exactly once.
    """
    merged = []
    seen = set()
    for chunks in chunk_lists:
        for c in chunks:
            key = (c.file_path, c.start_line, c.end_line)
            if key in seen:
                continue
            seen.add(key)
            merged.append(c)
    return merged


def format_chunks(chunks) -> str:
    if not chunks:
        return "No additional codebase context available."
    parts = []
    for c in chunks:
        parts.append(
            f"--- File: {c.file_path} "
            f"(lines {c.start_line}-{c.end_line}) ---\n{c.content}"
        )
    return "\n\n".join(parts)


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
    comment = None
    try:

        comment = post_placeholder_comment(repo_full_name, pr_number, installation_id)

        repo_id = upsert_repository(db, github_repo_id, repo_full_name, installation_id)
        pr_id = upsert_pull_request(
            db,
            repo_id,
            pr_number,
            pr_title,
            pr_author,
        )
        review_id = create_review(db, pr_id)

        diff = fetch_pr_diff(repo_full_name, pr_number, installation_id)
        if not diff:
            logger.warning(f"No diff found for PR #{pr_number}")
            update_comment(comment, "No reviewable changes found in this PR.")
            fail_review(db, review_id)
            return {"status": "skipped", "reason": "empty diff"}

        if repository_chunk_count(db, repo_id) == 0:
            logger.info(
                f"Repo {repo_full_name} not indexed yet, indexing inline "
                f"before reviewing PR #{pr_number}"
            )
            lock = redis_client.lock(INDEX_LOCK_KEY, timeout=INDEX_LOCK_TIMEOUT)
            if lock.acquire(blocking=True, blocking_timeout=INDEX_LOCK_TIMEOUT):
                try:
                    index_repository(repo_full_name, installation_id, repo_id)
                except Exception:
                    logger.exception(
                        "Inline indexing failed, reviewing without " "codebase context"
                    )
                finally:
                    try:
                        lock.release()
                    except Exception:
                        logger.warning("Index lock already expired on release")
            else:
                logger.warning(
                    "Could not acquire index lock, reviewing without context"
                )

        semantic_chunks = retrieve_relevant_chunks(diff, repo_id)
        definition_chunks = retrieve_symbol_definitions(diff, repo_id)
        chunks = merge_chunks(definition_chunks, semantic_chunks)
        context = format_chunks(chunks)
        logger.info(
            f"Retrieved {len(chunks)} context chunks for PR #{pr_number} "
            f"({len(definition_chunks)} from symbol resolution, "
            f"{len(semantic_chunks)} semantic)"
        )

        review = generate_review(diff, pr_title, context)
        update_comment(comment, review)
        complete_review(db, review_id, review)

        logger.info(f"Review posted to PR #{pr_number}")
        return {"status": "completed", "pr_number": pr_number}
    except Exception:
        logger.exception(f"Review failed for PR #{pr_number}")
        if comment is not None:
            try:
                update_comment(
                    comment,
                    "ReviewMind hit an error while analyzing this PR and "
                    "couldn't finish the review. Please try again shortly.",
                )
            except Exception:
                logger.exception("Failed to update placeholder after error")
        if review_id is not None:
            fail_review(db, review_id)
        raise
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="index_repository",
    autoretry_for=(ResourceExhausted,),
    max_retries=5,
    retry_backoff=120,
    retry_backoff_max=900,
    retry_jitter=True,
)
def index_repository_task(
    self, repo_full_name: str, installation_id: int, repository_id: int
):
    lock = redis_client.lock(INDEX_LOCK_KEY, timeout=INDEX_LOCK_TIMEOUT)
    if not lock.acquire(blocking=False):
        logger.info(f"Another indexing job is running, deferring {repo_full_name}")
        raise self.retry(
            countdown=INDEX_LOCK_RETRY_COUNTDOWN,
            max_retries=INDEX_LOCK_MAX_RETRIES,
        )

    try:
        logger.info(f"Worker picked up indexing job for {repo_full_name}")
        count = index_repository(repo_full_name, installation_id, repository_id)
        logger.info(f"Indexed {count} chunks for {repo_full_name}")
        return {"status": "completed", "chunks": count}
    finally:
        try:
            lock.release()
        except Exception:
            logger.warning("Index lock already expired on release")


@celery_app.task(
    bind=True,
    name="delta_index_repository",
    autoretry_for=(ResourceExhausted,),
    max_retries=5,
    retry_backoff=120,
    retry_backoff_max=900,
    retry_jitter=True,
)
def delta_index_repository_task(
    self,
    repo_full_name: str,
    pr_number: int,
    installation_id: int,
    repository_id: int,
):
    lock = redis_client.lock(INDEX_LOCK_KEY, timeout=INDEX_LOCK_TIMEOUT)
    if not lock.acquire(blocking=False):
        logger.info(
            f"Another indexing job is running, deferring delta-index for "
            f"{repo_full_name} PR #{pr_number}"
        )
        raise self.retry(
            countdown=INDEX_LOCK_RETRY_COUNTDOWN,
            max_retries=INDEX_LOCK_MAX_RETRIES,
        )

    try:
        logger.info(
            f"Worker picked up delta-index job for {repo_full_name} " f"PR #{pr_number}"
        )
        changed_paths = fetch_pr_changed_files(
            repo_full_name, pr_number, installation_id
        )
        count = index_changed_files(
            repo_full_name, installation_id, repository_id, changed_paths
        )
        logger.info(
            f"Delta-indexed {count} chunks from {len(changed_paths)} " "changed files"
        )
        return {"status": "completed", "chunks": count}
    finally:
        try:
            lock.release()
        except Exception:
            logger.warning("Index lock already expired on release")
