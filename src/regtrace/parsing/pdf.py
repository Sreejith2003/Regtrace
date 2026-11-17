"""PDF → section tree.

Headings are found with one of two strategies:

1. **bookmarks**: the PDF's own outline (table of contents), when it has one.
2. **fonts**: lines set noticeably larger than the body text are headings; each
   distinct heading size becomes a level (largest = level 1).

``strategy="auto"`` (the default) uses bookmarks when there are at least
``MIN_AUTO_BOOKMARKS`` of them, fonts otherwise.
Text between two headings belongs to the first one. Repeated page headers and
footers (and page numbers) are removed first.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pymupdf

from regtrace.tree import DocumentTree, Node, assign_ids

Strategy = Literal["auto", "bookmarks", "fonts"]

# A line counts as a heading if it is at least this many points larger than body text...
MIN_HEADING_SIZE_STEP = 1.0
# ...and no longer than this (long large-font lines are usually banners or quotes).
MAX_HEADING_CHARS = 120
# Heading sizes beyond this many distinct levels are folded into the deepest level.
MAX_HEADING_LEVELS = 4
# Top/bottom share of a page where headers and footers live.
PAGE_MARGIN = 0.08
# "auto" trusts bookmarks only if there are this many (one bookmark is just a title).
MIN_AUTO_BOOKMARKS = 2

_PAGE_NUMBER = re.compile(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", re.IGNORECASE)


@dataclass(frozen=True)
class _Line:
    text: str
    size: float  # font size of the line's dominant span, rounded to 0.5 pt
    page: int  # 1-based
    block: int  # document-wide block counter, to tell paragraphs apart
    y0: float
    y1: float
    page_height: float


@dataclass(frozen=True)
class _Heading:
    level: int  # 0 = document title (becomes the root title, not a node)
    title: str
    page: int
    start: int  # index of the first heading line in the line list
    end: int  # index after the last heading line (== start if not matched to a line)


@dataclass
class _Buffer:
    """Collects a node's own text lines, split into paragraphs by PDF block."""

    paragraphs: list[list[str]] = field(default_factory=list)
    last_block: int | None = None
    last_page: int | None = None

    def add(self, line: _Line) -> None:
        if line.block != self.last_block:
            self.paragraphs.append([])
        self.paragraphs[-1].append(line.text)
        self.last_block = line.block
        self.last_page = line.page

    def text(self) -> str:
        return "\n\n".join("\n".join(paragraph) for paragraph in self.paragraphs)


def parse_pdf(
    path: str | Path,
    *,
    doc_id: str | None = None,
    strategy: Strategy = "auto",
) -> DocumentTree:
    """Parse a PDF file into a `DocumentTree` (without summaries)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")

    with pymupdf.open(path) as doc:
        if not doc.is_pdf:
            raise ValueError(f"Not a PDF file: {path}")
        lines = _remove_page_furniture(_extract_lines(doc), doc.page_count)
        toc = doc.get_toc(simple=True)
        use_bookmarks = strategy == "bookmarks" or (
            strategy == "auto" and len(toc) >= MIN_AUTO_BOOKMARKS
        )
        headings = _bookmark_headings(toc, lines) if use_bookmarks else _font_headings(lines)

        metadata_title = _clean((doc.metadata or {}).get("title") or "")
        root = _build_tree(lines, headings, default_title=metadata_title or path.stem)
        root.page_start = 1
        root.page_end = max(doc.page_count, 1)

    assign_ids(root)
    return DocumentTree(
        doc_id=doc_id or _slug(path.stem),
        title=root.title,
        source=str(path),
        source_type="pdf",
        root=root,
    )


# --- extraction ---------------------------------------------------------------


def _extract_lines(doc: pymupdf.Document) -> list[_Line]:
    lines: list[_Line] = []
    block_no = 0
    for page_index, page in enumerate(doc):
        height = page.rect.height
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0:  # 0 = text, 1 = image
                continue
            block_no += 1
            for line in block["lines"]:
                spans = [span for span in line["spans"] if span["text"].strip()]
                if not spans:
                    continue
                text = _clean("".join(span["text"] for span in line["spans"]))
                dominant = max(spans, key=lambda span: len(span["text"].strip()))
                lines.append(
                    _Line(
                        text=text,
                        size=round(dominant["size"] * 2) / 2,
                        page=page_index + 1,
                        block=block_no,
                        y0=line["bbox"][1],
                        y1=line["bbox"][3],
                        page_height=height,
                    )
                )
    return lines


def _remove_page_furniture(lines: list[_Line], page_count: int) -> list[_Line]:
    """Drop page furniture from the top/bottom margins.

    Removed: page numbers ("3", "Page 3", "3 of 10", "3/10") on any page, and margin
    lines whose text (digits ignored) repeats on at least half the pages (min. 2).
    """

    def in_margin(line: _Line) -> bool:
        return line.y1 <= line.page_height * PAGE_MARGIN or line.y0 >= line.page_height * (
            1 - PAGE_MARGIN
        )

    def key(line: _Line) -> str:
        return re.sub(r"\d+", "#", line.text.lower())

    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        if in_margin(line):
            pages_by_key[key(line)].add(line.page)

    threshold = max(2, math.ceil(page_count / 2))
    repeated = {k for k, pages in pages_by_key.items() if len(pages) >= threshold}

    def is_furniture(line: _Line) -> bool:
        return in_margin(line) and (
            key(line) in repeated or _PAGE_NUMBER.fullmatch(line.text) is not None
        )

    return [line for line in lines if not is_furniture(line)]


# --- heading detection ----------------------------------------------------------


def _bookmark_headings(toc: list[list], lines: list[_Line]) -> list[_Heading]:
    """Place each bookmark at the line that matches its title, or at the top of its page."""
    headings: list[_Heading] = []
    cursor = 0
    for level, raw_title, page in toc:
        title = _clean(raw_title)
        if page < 1 or not title:  # bookmark without a target page
            continue
        match = None
        for k in range(cursor, len(lines)):
            if lines[k].page > page:
                break
            if lines[k].page == page and lines[k].text.casefold() == title.casefold():
                match = k
                break
        if match is not None:
            headings.append(_Heading(level, title, page, match, match + 1))
            cursor = match + 1
        else:
            pos = next((k for k in range(cursor, len(lines)) if lines[k].page >= page), len(lines))
            headings.append(_Heading(level, title, page, pos, pos))
            cursor = pos
    return headings


def _font_headings(lines: list[_Line]) -> list[_Heading]:
    if not lines:
        return []
    body_size = _body_size(lines)

    def is_candidate(k: int) -> bool:
        line = lines[k]
        return (
            line.size >= body_size + MIN_HEADING_SIZE_STEP and len(line.text) <= MAX_HEADING_CHARS
        )

    # Group consecutive candidate lines of the same size in the same block (wrapped headings).
    groups: list[tuple[int, int]] = []
    k = 0
    while k < len(lines):
        if not is_candidate(k):
            k += 1
            continue
        end = k + 1
        while (
            end < len(lines)
            and is_candidate(end)
            and lines[end].block == lines[k].block
            and lines[end].size == lines[k].size
        ):
            end += 1
        groups.append((k, end))
        k = end

    def group_title(group: tuple[int, int]) -> str:
        return " ".join(lines[i].text for i in range(*group))

    headings: list[_Heading] = []
    # A unique largest heading that comes first is the document title, not a section.
    sizes = [lines[start].size for start, _ in groups]
    if len(groups) > 1 and sizes[0] == max(sizes) and sizes.count(sizes[0]) == 1:
        start, end = groups.pop(0)
        headings.append(_Heading(0, group_title((start, end)), lines[start].page, start, end))

    distinct_sizes = sorted({lines[start].size for start, _ in groups}, reverse=True)
    level_of = {
        size: min(rank, MAX_HEADING_LEVELS) for rank, size in enumerate(distinct_sizes, start=1)
    }
    for start, end in groups:
        line = lines[start]
        headings.append(
            _Heading(level_of[line.size], group_title((start, end)), line.page, start, end)
        )
    return headings


def _body_size(lines: list[_Line]) -> float:
    """The font size that carries the most characters."""
    chars_by_size: Counter[float] = Counter()
    for line in lines:
        chars_by_size[line.size] += len(line.text)
    return chars_by_size.most_common(1)[0][0]


# --- tree building --------------------------------------------------------------


def _build_tree(lines: list[_Line], headings: list[_Heading], *, default_title: str) -> Node:
    root = Node(title=default_title)
    buffers: dict[int, _Buffer] = {id(root): _Buffer()}
    stack: list[tuple[int, Node]] = [(0, root)]
    heading_lines = {k for h in headings for k in range(h.start, h.end)}
    ordered = sorted(headings, key=lambda h: h.start)  # stable: keeps bookmark order on ties

    next_heading = 0
    for k in range(len(lines) + 1):
        while next_heading < len(ordered) and ordered[next_heading].start == k:
            heading = ordered[next_heading]
            next_heading += 1
            if heading.level == 0:
                root.title = heading.title
                continue
            while stack[-1][0] >= heading.level:
                stack.pop()
            node = Node(title=heading.title, page_start=heading.page)
            stack[-1][1].children.append(node)
            stack.append((heading.level, node))
            buffers[id(node)] = _Buffer()
        if k == len(lines):
            break
        if k not in heading_lines:
            buffers[id(stack[-1][1])].add(lines[k])

    _fill(root, buffers)
    return root


def _fill(node: Node, buffers: dict[int, _Buffer]) -> int | None:
    """Write each node's text and set page_end to the last page its subtree covers."""
    buffer = buffers[id(node)]
    node.text = buffer.text()
    pages = [p for p in (node.page_start, buffer.last_page) if p is not None]
    for child in node.children:
        child_end = _fill(child, buffers)
        if child_end is not None:
            pages.append(child_end)
    node.page_end = max(pages) if pages else None
    return node.page_end


# --- helpers ----------------------------------------------------------------------


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "document"
