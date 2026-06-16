import logging
import os
from dataclasses import dataclass

import google.generativeai as genai
from dotenv import load_dotenv
from github import Auth, GithubIntegration
from sqlalchemy import select

from app.db.session import SyncSessionLocal
from app.models.models import CodeChunk

load_dotenv()
logger = logging.getLogger(__name__)

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "0")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH", "")

WINDOW_SIZE = 40
OVERLAP_SIZE = 10
STEP = WINDOW_SIZE - OVERLAP_SIZE

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768

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


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    response = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=texts,
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )
    return response["embedding"]


def should_index(path: str) -> bool:
    if any(skip in path for skip in SKIP_PATHS):
        return False
    if path.endswith(SKIP_SUFFIXES):
        return False
    return path.endswith(ALLOWED_EXTENSIONS)


def fetch_repository_files(repo_full_name: str, installation_id: int) -> list[dict]:
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    auth = Auth.AppAuth(GITHUB_APP_ID, private_key)
    gi = GithubIntegration(auth=auth)
    github_client = gi.get_github_for_installation(installation_id)

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
        db.query(CodeChunk).filter(CodeChunk.repository_id == repository_id).delete()
        db.commit()

        files = fetch_repository_files(repo_full_name, installation_id)

        total_chunks = 0
        for file in files:
            chunks = chunk_code(file["content"])
            if not chunks:
                continue

            vectors = embed_texts([c.content for c in chunks])

            for chunk, vector in zip(chunks, vectors):
                db.add(
                    CodeChunk(
                        repository_id=repository_id,
                        file_path=file["path"],
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


def retrieve_relevant_chunks(
    diff: str, repository_id: int, top_k: int = 5
) -> list[CodeChunk]:
    query_vector = embed_texts([diff])[0]

    db = SyncSessionLocal()
    try:
        stmt = (
            select(CodeChunk)
            .where(CodeChunk.repository_id == repository_id)
            .order_by(CodeChunk.embedding.cosine_distance(query_vector))
            .limit(top_k)
        )
        results = db.execute(stmt).scalars().all()
        return results
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
