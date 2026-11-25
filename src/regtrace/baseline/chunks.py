"""Fixed-size overlapping chunks of a policy, the way a normal RAG pipeline splits text."""

from __future__ import annotations

from pydantic import BaseModel

from regtrace.tree import DocumentTree

CHUNK_CHARS = 1000
OVERLAP_CHARS = 150


class Chunk(BaseModel):
    id: str
    text: str
    section_ids: list[str]


def linearize(tree: DocumentTree) -> tuple[str, list[tuple[int, int, str]]]:
    """The whole document as one string, plus the character span of every node."""
    parts: list[str] = []
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for node in tree.walk():
        piece = "\n\n".join(t for t in (node.title, node.text) if t)
        if not piece:
            continue
        if parts:
            pos += 2
        spans.append((pos, pos + len(piece), node.id))
        parts.append(piece)
        pos += len(piece)
    return "\n\n".join(parts), spans


def chunk_tree(
    tree: DocumentTree, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS
) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than the chunk size")
    text, spans = linearize(tree)
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(
                text.rfind(" ", start + size // 2, end), text.rfind("\n", start + size // 2, end)
            )
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            ids = [node_id for s, e, node_id in spans if s < end and e > start]
            chunks.append(Chunk(id=f"c{len(chunks) + 1}", text=piece, section_ids=ids))
        if end >= len(text):
            break
        nxt = end - overlap
        space = text.find(" ", nxt, end)
        start = max(space + 1 if space != -1 else nxt, start + 1)
    return chunks
