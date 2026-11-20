"""Bottom-up LLM summaries for every node of a section tree.

Summaries are what the evidence finder reads when it navigates a tree
(`DocumentTree.outline()`), so they describe *what a section covers*, never
whether it is compliant.

Order is post-order (children before parents): a leaf is summarized from its
own text, a parent from its own text plus its children's summaries. That keeps
every prompt small and makes a parent's summary describe its whole subtree.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from regtrace.llm import LLMClient, LLMConnectionError, LLMError
from regtrace.tree.models import DocumentTree, Node

DEFAULT_MAX_CHARS = 6000  # ~1.5k tokens of section text; fits num_ctx=8192 with room to spare
TRUNCATION_MARK = "\n[... text truncated ...]"

SYSTEM_PROMPT = (
    "You write short, factual summaries of document sections for a table of contents. "
    "A reader uses them to decide which section to open. Describe only what the section "
    "covers. Do not judge it, give advice, or add anything that is not in the text."
)


class NodeSummary(BaseModel):
    """The structured reply the model must return for one node."""

    summary: str = Field(min_length=1)


@dataclass
class SummaryStats:
    """What happened during one `summarize_tree` run."""

    summarized: int = 0
    skipped: int = 0  # nodes with no content to summarize
    failed: list[str] = field(default_factory=list)  # ids of nodes whose LLM call failed


ProgressCallback = Callable[[int, int, Node], None]


def summarize_tree(
    tree: DocumentTree,
    client: LLMClient,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    on_progress: ProgressCallback | None = None,
) -> SummaryStats:
    """Fill `summary` on every node of `tree` in place, children before parents.

    - Nodes with no text and no summarized children are skipped (summary stays `None`).
    - A failed LLM call leaves that node's summary `None` and the run continues;
      its parent then sees the child's title instead of a summary.
    - `LLMConnectionError` is re-raised: if the server is down, every call would fail.

    `on_progress(done, total, node)` is called before each node is processed.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")

    order = _post_order(tree.root)
    stats = SummaryStats()
    for done, node in enumerate(order, start=1):
        if on_progress is not None:
            on_progress(done, len(order), node)

        if not node.text.strip() and not any(child.summary for child in node.children):
            node.summary = None
            stats.skipped += 1
            continue

        prompt = build_prompt(tree, node, max_chars=max_chars)
        try:
            result = client.generate_structured(prompt, NodeSummary, system=SYSTEM_PROMPT)
        except LLMConnectionError:
            raise
        except LLMError:
            node.summary = None
            stats.failed.append(node.id)
            continue

        node.summary = " ".join(result.summary.split())  # collapse stray newlines/spaces
        stats.summarized += 1
    return stats


def build_prompt(tree: DocumentTree, node: Node, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Return the user prompt for summarizing `node` (its own text + children's summaries)."""
    is_root = node is tree.root
    lines = [f"Document: {tree.title}"]
    lines.append("Section: (the whole document)" if is_root else f"Section: {node.title}")

    text = node.text.strip()
    if text:
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + TRUNCATION_MARK
        lines += ["", "Section text:", '"""', text, '"""']

    if node.children:
        lines += ["", "Subsections:"]
        for child in node.children:
            entry = f"- {child.title}"
            if child.summary:
                entry += f": {child.summary}"
            lines.append(entry)

    target = "the whole document" if is_root else "this section"
    lines += [
        "",
        f"Write one or two sentences (at most 40 words) naming the specific topics {target} "
        "covers, for example which kinds of personal data, purposes, recipients, rights, "
        'time limits or contact details. Reply with JSON: {"summary": "..."}',
    ]
    return "\n".join(lines)


def _post_order(node: Node) -> list[Node]:
    nodes: list[Node] = []
    for child in node.children:
        nodes.extend(_post_order(child))
    nodes.append(node)
    return nodes
