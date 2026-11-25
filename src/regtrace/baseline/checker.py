"""Check obligations with plain chunked RAG: retrieve top-k chunks, then the same judge."""

from __future__ import annotations

import time

from regtrace.baseline.chunks import Chunk
from regtrace.baseline.retriever import ChunkIndex
from regtrace.evidence.checker import ProgressCallback, check_policy, finish_finding, new_finding
from regtrace.evidence.judge import judge
from regtrace.evidence.models import ConditionMet, Finding, Match, Report
from regtrace.llm import LLMClient, LLMConnectionError, LLMError
from regtrace.regulations import LinkedObligation, LinkResult
from regtrace.tree import DocumentTree
from regtrace.verify.quotes import match_text

TOP_K = 8


def query_text(item: LinkedObligation) -> str:
    o = item.obligation
    return " ".join(p for p in (f"{o.title}.", o.what, o.evidence) if p)


def chunk_evidence(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[section {c.id}]\n{c.text}" for c in chunks)


def check_obligation_chunked(
    policy: DocumentTree,
    item: LinkedObligation,
    client: LLMClient,
    *,
    index: ChunkIndex,
    regulation: DocumentTree | None = None,
    assume: ConditionMet | None = None,
    k: int = TOP_K,
) -> Finding:
    finding = new_finding(item, assume)
    if finding.status is not None:
        return finding

    start = time.perf_counter()
    try:
        hits = [chunk for chunk, _ in index.search(query_text(item), k)]
        reply = judge(item, chunk_evidence(hits), client, regulation=regulation, allow_more=False)
        finding.llm_calls = 1
    except LLMConnectionError:
        raise
    except LLMError as exc:
        finding.error = str(exc)
        finding.seconds = round(time.perf_counter() - start, 1)
        return finding

    finding.sections_read = list(dict.fromkeys(i for c in hits for i in c.section_ids))
    finish_finding(finding, item, reply, assume)
    by_id = {c.id: c for c in index.chunks}
    for quote in finding.quotes:
        chunk = by_id.get(quote.section_id)
        if chunk is not None:
            quote.section_id = section_of(policy, chunk, quote.text)
    finding.seconds = round(time.perf_counter() - start, 1)
    return finding


def section_of(policy: DocumentTree, chunk: Chunk, quote: str) -> str:
    """The policy section a quote from this chunk belongs to, so citations stay comparable."""
    for node_id in reversed(chunk.section_ids):
        node = policy.get(node_id)
        text = "\n\n".join(t for t in (node.title, node.text) if t)
        if match_text(quote, text).match != Match.not_found:
            return node_id
    return chunk.section_ids[0] if chunk.section_ids else policy.root.id


def check_policy_chunked(
    policy: DocumentTree,
    links: LinkResult,
    client: LLMClient,
    index: ChunkIndex,
    *,
    regulation: DocumentTree | None = None,
    only: list[str] | None = None,
    assume: dict[str, ConditionMet] | None = None,
    on_progress: ProgressCallback | None = None,
    k: int = TOP_K,
) -> Report:
    def check(policy, item, client, *, regulation=None, assume=None):
        return check_obligation_chunked(
            policy, item, client, index=index, regulation=regulation, assume=assume, k=k
        )

    return check_policy(
        policy,
        links,
        client,
        regulation=regulation,
        only=only,
        assume=assume,
        on_progress=on_progress,
        check=check,
        method="chunked",
    )
