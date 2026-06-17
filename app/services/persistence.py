import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import func

from app.models.models import CodeChunk, PullRequest, Repository, Review, ReviewStatus

logger = logging.getLogger(__name__)


def upsert_repository(db, github_repo_id, full_name, installation_id):
    stmt = (
        insert(Repository)
        .values(
            github_repo_id=github_repo_id,
            full_name=full_name,
            installation_id=installation_id,
        )
        .on_conflict_do_update(
            index_elements=["github_repo_id"],
            set_={"full_name": full_name, "installation_id": installation_id},
        )
        .returning(Repository.id)
    )
    repo_id = db.execute(stmt).scalar_one()
    db.commit()
    return repo_id


def upsert_pull_request(db, repo_id, github_pr_number, title, author):
    stmt = (
        insert(PullRequest)
        .values(
            repo_id=repo_id,
            github_pr_number=github_pr_number,
            title=title,
            author=author,
        )
        .on_conflict_do_update(
            constraint="uq_pr_repo_number",
            set_={"title": title, "author": author},
        )
        .returning(PullRequest.id)
    )
    pr_id = db.execute(stmt).scalar_one()
    db.commit()
    return pr_id


def repository_chunk_count(db, repository_id):
    return db.query(CodeChunk).filter(CodeChunk.repository_id == repository_id).count()


def delete_repository_chunks(db, repository_id):
    deleted = (
        db.query(CodeChunk).filter(CodeChunk.repository_id == repository_id).delete()
    )
    db.commit()
    return deleted


def create_review(db, pull_request_id):
    review = Review(
        pull_request_id=pull_request_id,
        status=ReviewStatus.processing,
    )
    db.add(review)
    db.commit()
    return review.id


def complete_review(db, review_id, summary):
    review = db.get(Review, review_id)
    review.status = ReviewStatus.completed
    review.summary = summary
    review.posted_at = func.now()
    db.commit()


def fail_review(db, review_id):
    review = db.get(Review, review_id)
    review.status = ReviewStatus.failed
    db.commit()
