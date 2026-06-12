from dataclasses import dataclass

WINDOW_SIZE = 40
OVERLAP_SIZE = 10
STEP = WINDOW_SIZE - OVERLAP_SIZE


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
