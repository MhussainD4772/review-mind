import logging
import os
import re
import time
from dataclasses import dataclass

import google.generativeai as genai
from dotenv import load_dotenv
from github import Auth, GithubIntegration
from google.api_core.exceptions import ResourceExhausted
from sqlalchemy import select

from app.core.github_auth import get_github_for_installation
from app.db.session import SyncSessionLocal
from app.models.models import CodeChunk
from app.services.symbols import build_definition_pattern, extract_referenced_symbols

load_dotenv()
logger = logging.getLogger(__name__)

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "0")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH", "")

WINDOW_SIZE = 40
OVERLAP_SIZE = 10
STEP = WINDOW_SIZE - OVERLAP_SIZE

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768

# Embedding API pacing. The free tier rate-limits per minute (both requests
# and tokens), so we send chunks in modest batches with a gap between calls
# and back off on 429s long enough to outlast a one-minute reset window
# instead of firing one request per file as fast as possible.
EMBED_BATCH_SIZE = 20
EMBED_BATCH_DELAY_SECONDS = 8.0
EMBED_MAX_RETRIES = 8
EMBED_MAX_BACKOFF_SECONDS = 65.0

ALLOWED_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx")

SKIP_PATHS = (
    "node_modules/",
    "dist/",
    "build/",
    "__pycache__/",
    ".venv/",
)

SKIP_SUFFIXES = (".min.js",)


@dataclass
class Chunk:
    content: str
    start_line: int
    end_line: int


def chunk_code(code: str) -> list[Chunk]:
    lines = code.splitlines()
    total = len(lines)

    if total == 0:
        return []

    chunks = []
    start = 0
    while start < total:
        end = min(start + WINDOW_SIZE, total)
        window_lines = lines[start:end]
        chunks.append(
            Chunk(
                content="\n".join(window_lines),
                start_line=start + 1,
                end_line=end,
            )
        )
        if end == total:
            break
        start += STEP

    return chunks


def _embed_batch_with_retry(batch: list[str]) -> list[list[float]]:
    delay = 2.0
    for attempt in range(EMBED_MAX_RETRIES):
        try:
            response = genai.embed_content(
                model=EMBEDDING_MODEL,
                content=batch,
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=EMBEDDING_DIMENSIONS,
            )
            return response["embedding"]
        except ResourceExhausted:
            if attempt == EMBED_MAX_RETRIES - 1:
                raise
            logger.warning(
                f"Embedding rate-limited, backing off {delay:.0f}s "
                f"(attempt {attempt + 1}/{EMBED_MAX_RETRIES})"
            )
            time.sleep(delay)
            delay = min(delay * 2, EMBED_MAX_BACKOFF_SECONDS)
    return []


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        embeddings.extend(_embed_batch_with_retry(batch))
        if i + EMBED_BATCH_SIZE < len(texts):
            time.sleep(EMBED_BATCH_DELAY_SECONDS)
    return embeddings


def embed_query(text: str) -> list[float]:
    response = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )
    return response["embedding"]


def clean_diff_for_embedding(diff: str) -> str:
    """Strip diff syntax so the query embedding reflects real code, not noise.

    Removes hunk headers, file markers, and the leading +/- columns so the
    vector captures the semantics of the changed code rather than diff
    formatting characters.
    """
    cleaned_lines = []
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ", "@@", "diff --git", "index ")):
            continue
        if line.startswith(("+", "-")):
            cleaned_lines.append(line[1:])
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def should_index(path: str) -> bool:
    if any(skip in path for skip in SKIP_PATHS):
        return False
    if path.endswith(SKIP_SUFFIXES):
        return False
    return path.endswith(ALLOWED_EXTENSIONS)


def fetch_repository_files(repo_full_name: str, installation_id: int) -> list[dict]:
    github_client = get_github_for_installation(installation_id)

    repo = github_client.get_repo(repo_full_name)
    default_branch = repo.default_branch
    tree = repo.get_git_tree(default_branch, recursive=True)

    files = []
    for element in tree.tree:
        if element.type != "blob":
            continue
        if not should_index(element.path):
            continue

        file_content = repo.get_contents(element.path, ref=default_branch)
        content = file_content.decoded_content.decode("utf-8", errors="replace")
        files.append({"path": element.path, "content": content})

    return files


def index_repository(
    repo_full_name: str, installation_id: int, repository_id: int
) -> int:
    db = SyncSessionLocal()
    try:
        files = fetch_repository_files(repo_full_name, installation_id)

        pending = []
        for file in files:
            for chunk in chunk_code(file["content"]):
                pending.append((file["path"], chunk))

        # Embed everything before touching the DB. If embedding fails (e.g. the
        # daily quota is exhausted), we abort without having deleted the
        # existing index, so a failed re-index never leaves the repo empty.
        vectors = embed_texts([chunk.content for _, chunk in pending])

        db.query(CodeChunk).filter(CodeChunk.repository_id == repository_id).delete()

        for (path, chunk), vector in zip(pending, vectors):
            db.add(
                CodeChunk(
                    repository_id=repository_id,
                    file_path=path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    embedding=vector,
                )
            )

        db.commit()
        return len(pending)
    finally:
        db.close()


FILE_MARKER = re.compile(r"^--- .* ---$")


def split_diff_by_file(diff: str) -> list[str]:
    """Split a multi-file diff into per-file segments.

    ``fetch_pr_diff`` prefixes each file's patch with a ``--- path ---`` marker.
    Retrieving context per file (rather than embedding the whole diff at once)
    keeps each query focused so a change in one file can't drown out the
    context another file needs.
    """
    segments: list[str] = []
    current: list[str] = []
    for line in diff.splitlines():
        if FILE_MARKER.match(line):
            if current:
                segments.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        segments.append("\n".join(current))
    return segments


def _query_chunks(
    db, query_text: str, repository_id: int, limit: int
) -> list[CodeChunk]:
    cleaned = clean_diff_for_embedding(query_text)
    if not cleaned.strip():
        return []
    query_vector = embed_query(cleaned)
    stmt = (
        select(CodeChunk)
        .where(CodeChunk.repository_id == repository_id)
        .order_by(CodeChunk.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    return db.execute(stmt).scalars().all()


def retrieve_relevant_chunks(
    diff: str,
    repository_id: int,
    top_k: int = 10,
    per_file_k: int = 4,
) -> list[CodeChunk]:
    segments = split_diff_by_file(diff)

    db = SyncSessionLocal()
    try:
        if len(segments) <= 1:
            return _query_chunks(db, diff, repository_id, top_k)

        merged: list[CodeChunk] = []
        seen: set[int] = set()
        for segment in segments:
            for chunk in _query_chunks(db, segment, repository_id, per_file_k):
                if chunk.id in seen:
                    continue
                seen.add(chunk.id)
                merged.append(chunk)
        return merged[:top_k]
    finally:
        db.close()


def retrieve_symbol_definitions(
    diff: str, repository_id: int, max_chunks: int = 6
) -> list[CodeChunk]:
    """Fetch chunks that define symbols referenced by the diff.

    This is exact-symbol resolution, not fuzzy similarity: it finds where the
    functions/types/imports touched by the change are actually defined, which
    is what catches cross-file bugs (wrong status value, missing field, a
    clamped setter) that embedding retrieval blurs over.
    """
    symbols = extract_referenced_symbols(diff)
    pattern = build_definition_pattern(symbols)
    if pattern is None:
        return []

    db = SyncSessionLocal()
    try:
        stmt = (
            select(CodeChunk)
            .where(CodeChunk.repository_id == repository_id)
            .where(CodeChunk.content.op("~")(pattern))
            .limit(max_chunks)
        )
        return db.execute(stmt).scalars().all()
    finally:
        db.close()


def index_changed_files(
    repo_full_name: str,
    installation_id: int,
    repository_id: int,
    changed_paths: list[str],
) -> int:
    paths_to_index = [p for p in changed_paths if should_index(p)]
    if not paths_to_index:
        return 0

    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    auth = Auth.AppAuth(GITHUB_APP_ID, private_key)
    gi = GithubIntegration(auth=auth)
    github_client = gi.get_github_for_installation(installation_id)
    repo = github_client.get_repo(repo_full_name)
    default_branch = repo.default_branch

    db = SyncSessionLocal()
    try:
        total_chunks = 0
        for path in paths_to_index:
            db.query(CodeChunk).filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.file_path == path,
            ).delete()

            try:
                file_content = repo.get_contents(path, ref=default_branch)
            except Exception:
                logger.warning(f"Could not fetch {path}, skipping")
                continue

            content = file_content.decoded_content.decode("utf-8", errors="replace")
            chunks = chunk_code(content)
            if not chunks:
                continue

            vectors = embed_texts([c.content for c in chunks])
            for chunk, vector in zip(chunks, vectors):
                db.add(
                    CodeChunk(
                        repository_id=repository_id,
                        file_path=path,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        content=chunk.content,
                        embedding=vector,
                    )
                )
            total_chunks += len(chunks)

        db.commit()
        return total_chunks
    finally:
        db.close()
