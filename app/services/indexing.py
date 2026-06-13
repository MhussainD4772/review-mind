from dataclasses import dataclass

import google.generativeai as genai

WINDOW_SIZE = 40
OVERLAP_SIZE = 10
STEP = WINDOW_SIZE - OVERLAP_SIZE

EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768


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
