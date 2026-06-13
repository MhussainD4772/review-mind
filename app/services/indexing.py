import os
from dataclasses import dataclass

import google.generativeai as genai
from dotenv import load_dotenv
from github import Auth, GithubIntegration

load_dotenv()

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
