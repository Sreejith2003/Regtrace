"""Pick the policy sections worth reading for one obligation, like skimming a table of contents."""

from __future__ import annotations

from pydantic import BaseModel, Field

from regtrace.llm import LLMClient
from regtrace.regulations import LinkedObligation
from regtrace.tree import DocumentTree, Node

MAX_OUTLINE_CHARS = 12000
SNIPPET_CHARS = 120
MAX_SECTIONS = 4
SECTION_CHARS = 3500
EVIDENCE_CHARS = 9000

SYSTEM_PROMPT = (
    "You help a compliance analyst find where a privacy policy deals with a legal requirement. "
    "You only choose sections to read; you do not judge them."
)


class SectionChoice(BaseModel):
    section_ids: list[str] = Field(default_factory=list)
    reason: str = ""


def navigation_outline(tree: DocumentTree, max_chars: int = MAX_OUTLINE_CHARS) -> str:
    """The outline the model navigates with; text snippets stand in for missing summaries."""
    depth = max((node.level for node in tree.walk()), default=0)
    while True:
        lines = [_outline_line(node) for node in tree.walk() if 0 < node.level <= depth]
        outline = "\n".join(lines)
        if len(outline) <= max_chars or depth <= 1:
            return outline[:max_chars]
        depth -= 1


def titles_outline(tree: DocumentTree, max_chars: int = 3000) -> str:
    lines = [f"{'  ' * (n.level - 1)}{n.id}  {n.short_title}" for n in tree.walk() if n.level]
    return "\n".join(lines)[:max_chars]


def choose_sections(tree: DocumentTree, item: LinkedObligation, client: LLMClient) -> SectionChoice:
    if not tree.root.children:
        return SectionChoice(section_ids=[tree.root.id], reason="The document has no sections.")
    o = item.obligation
    prompt = "\n".join(
        [
            f"Privacy policy: {tree.title}",
            "",
            "Requirement:",
            f"- {o.title} (GDPR Art. {o.ref})",
            f"- What the policy must say: {o.what}",
            f"- Typical evidence: {o.evidence or '-'}",
            "",
            "Policy outline (section id, heading, summary):",
            navigation_outline(tree),
            "",
            f"Which sections (at most {MAX_SECTIONS}) most likely contain information for this "
            "requirement? Prefer specific subsections. If nothing fits, pick the closest ones. "
            'Reply with JSON: {"section_ids": ["2.1", ...], "reason": "..."}',
        ]
    )
    choice = client.generate_structured(prompt, SectionChoice, system=SYSTEM_PROMPT)
    return SectionChoice(section_ids=valid_ids(tree, choice.section_ids), reason=choice.reason)


def valid_ids(tree: DocumentTree, ids: list[str], limit: int = MAX_SECTIONS) -> list[str]:
    known = {node.id for node in tree.walk()}
    cleaned = [i.strip().removeprefix("section").strip() for i in ids]
    return list(dict.fromkeys(i for i in cleaned if i in known))[:limit]


def read_sections(tree: DocumentTree, ids: list[str], budget: int = EVIDENCE_CHARS) -> str:
    """Section texts (with their subsections) labelled by id, within a character budget."""
    parts: list[str] = []
    used = 0
    for node_id in ids:
        node = tree.get(node_id)
        text = tree.full_text(node_id)
        if node is not tree.root and text.startswith(node.title):
            text = text[len(node.title) :].lstrip()
        room = min(SECTION_CHARS, budget - used)
        if room <= 200:
            break
        if len(text) > room:
            text = text[:room].rstrip() + " [...]"
        label = "whole document" if node is tree.root else node.title
        parts.append(f"[section {node_id}] {label}\n{text}")
        used += len(text)
    return "\n\n".join(parts)


def _outline_line(node: Node) -> str:
    indent = "  " * (node.level - 1)
    line = f"{indent}{node.id}  {node.short_title}"
    if node.summary:
        return f"{line}: {node.summary}"
    snippet = " ".join(node.text.split())[:SNIPPET_CHARS]
    return f"{line}: {snippet}..." if snippet else line
