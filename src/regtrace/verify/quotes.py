"""Find a quote from the judge in the policy text it claims to come from."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from regtrace.evidence.models import Match
from regtrace.tree import DocumentTree, Node

FUZZY_COVERAGE = 0.75
MIN_BLOCK = 2

_WORD = re.compile(r"\w+")
_TRIM = re.compile(r"^[\s\"'“”‘’«»]+|(?:\s*(?:\[\s*(?:\.\.\.|…)\s*\]|\.\.\.|…))?[\s\"'“”‘’«»]*$")
_RANK = {Match.exact: 4, Match.normalized: 3, Match.spliced: 2, Match.fuzzy: 1, Match.not_found: 0}


@dataclass
class Located:
    match: Match
    section_id: str | None = None
    text: str = ""
    coverage: float = 0.0

    def beats(self, other: Located) -> bool:
        return (_RANK[self.match], self.coverage) > (_RANK[other.match], other.coverage)


def clean_quote(text: str) -> str:
    return _TRIM.sub("", text.strip())


def words(text: str) -> list[tuple[str, int, int]]:
    return [
        (unicodedata.normalize("NFKC", m.group()).casefold(), m.start(), m.end())
        for m in _WORD.finditer(text)
    ]


def match_text(quote: str, text: str) -> Located:
    quote = clean_quote(quote)
    q = [w for w, _, _ in words(quote)]
    if not q or not text:
        return Located(Match.not_found)

    exact = re.search(r"\s+".join(map(re.escape, quote.split())), text)
    if exact:
        return Located(Match.exact, text=exact.group(), coverage=1.0)

    doc = words(text)
    matcher = SequenceMatcher(None, [w for w, _, _ in doc], q, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size >= min(MIN_BLOCK, len(q))]
    if not blocks:
        return Located(Match.not_found)
    spread = blocks[-1].a + blocks[-1].size - blocks[0].a
    if len(blocks) > 1 and spread > 3 * len(q) + 30:
        blocks = [max(blocks, key=lambda b: b.size)]

    coverage = sum(b.size for b in blocks) / len(q)
    source = text[doc[blocks[0].a][1] : doc[blocks[-1].a + blocks[-1].size - 1][2]]
    if coverage == 1.0:
        match = Match.normalized if len(blocks) == 1 else Match.spliced
    elif coverage >= FUZZY_COVERAGE:
        match = Match.fuzzy
    else:
        return Located(Match.not_found, coverage=coverage)
    return Located(match, text=source, coverage=round(coverage, 3))


def locate(
    policy: DocumentTree, quote: str, section_id: str, prefer: list[str] | None = None
) -> Located:
    """Look in the cited section first, then in the preferred sections, then everywhere."""
    section_id = section_id.strip().removeprefix("section").strip()
    nodes = {node.id: node for node in policy.walk()}
    best = Located(Match.not_found)
    if section_id in nodes:
        best = _match_node(policy, nodes[section_id], quote)
        if _RANK[best.match] >= _RANK[Match.spliced]:
            return best

    preferred = {n.id for i in prefer or [] if i in nodes for n in nodes[i].walk()}
    order = sorted(
        (n for n in nodes.values() if n.id != section_id),
        key=lambda n: (n.id not in preferred, -n.level),
    )
    for node in order:
        found = _match_node(policy, node, quote)
        if found.beats(best):
            best = found
            if best.match == Match.exact:
                break
    return best


def _match_node(policy: DocumentTree, node: Node, quote: str) -> Located:
    if node is policy.root and node.children:
        text = "\n\n".join(t for t in (node.title, node.text) if t)
    else:
        text = policy.full_text(node.id)
    found = match_text(quote, text)
    if found.match != Match.not_found:
        found.section_id = node.id
    return found
