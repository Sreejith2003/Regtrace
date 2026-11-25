"""Embed chunks and return the most similar ones for a query (cosine similarity, in memory)."""

from __future__ import annotations

import math

from regtrace.baseline.chunks import Chunk
from regtrace.llm import Embedder

BATCH = 16


def _prefixes(model: str) -> tuple[str, str]:
    if "nomic" in model:
        return "search_document: ", "search_query: "
    return "", ""


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class ChunkIndex:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]], embedder: Embedder):
        if len(chunks) != len(vectors):
            raise ValueError("one vector per chunk is needed")
        self.chunks = chunks
        self.vectors = [_unit(v) for v in vectors]
        self.embedder = embedder

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder) -> ChunkIndex:
        doc_prefix, _ = _prefixes(embedder.embed_model)
        vectors: list[list[float]] = []
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i : i + BATCH]
            vectors += embedder.embed([doc_prefix + c.text for c in batch])
        return cls(chunks, vectors, embedder)

    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        _, query_prefix = _prefixes(self.embedder.embed_model)
        q = _unit(self.embedder.embed([query_prefix + query])[0])
        scored = [
            (chunk, sum(a * b for a, b in zip(q, v, strict=True)))
            for chunk, v in zip(self.chunks, self.vectors, strict=True)
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]
