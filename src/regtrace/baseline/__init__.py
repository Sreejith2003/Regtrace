"""Chunked RAG baseline to compare the tree method against."""

from regtrace.baseline.checker import (
    TOP_K,
    check_obligation_chunked,
    check_policy_chunked,
    chunk_evidence,
    query_text,
    section_of,
)
from regtrace.baseline.chunks import CHUNK_CHARS, OVERLAP_CHARS, Chunk, chunk_tree, linearize
from regtrace.baseline.retriever import ChunkIndex

__all__ = [
    "CHUNK_CHARS",
    "OVERLAP_CHARS",
    "TOP_K",
    "Chunk",
    "ChunkIndex",
    "check_obligation_chunked",
    "check_policy_chunked",
    "chunk_evidence",
    "chunk_tree",
    "linearize",
    "query_text",
    "section_of",
]
