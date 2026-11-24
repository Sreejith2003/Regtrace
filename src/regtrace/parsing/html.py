"""HTML → section tree, using <h1>–<h6> as headings."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from regtrace.tree import DocumentTree, Node, assign_ids

USER_AGENT = "RegTrace/0.1 (privacy policy research tool; python-httpx)"

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = (
    {"p", "div", "section", "article", "main", "blockquote", "pre", "address", "hr"}
    | {"ul", "ol", "li", "dl", "dt", "dd"}
    | {"table", "tr", "td", "th", "figure", "figcaption"}
)
_DROP = ["script", "style", "noscript", "template", "svg", "nav", "aside", "form", "iframe"]

Item = tuple[int, str]


def fetch_html(url: str, *, timeout: float = 30.0) -> str:
    response = httpx.get(
        url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout
    )
    response.raise_for_status()
    return response.text


def parse_html_file(path: str | Path, *, doc_id: str | None = None) -> DocumentTree:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    html = path.read_text(encoding="utf-8", errors="replace")
    return parse_html(html, source=str(path), doc_id=doc_id or _slug(path.stem))


def parse_html(html: str, *, source: str, doc_id: str) -> DocumentTree:
    soup = BeautifulSoup(html, "html.parser")
    page_title = _clean(soup.title.get_text()) if soup.title else ""
    for tag in soup.find_all(_DROP):
        tag.decompose()
    for tag in soup.find_all(["header", "footer"]):
        if not tag.find_parent(["main", "article"]):
            tag.decompose()
    content = soup.find("main") or soup.find("article") or soup.body or soup

    items: list[Item] = []
    buffer: list[str] = []
    _collect(content, items, buffer)
    _flush(items, buffer)

    root = Node(title=page_title or doc_id)
    levels = [level for level, _ in items if level]
    if items and items[0][0] == 1 and levels.count(1) == 1:
        root.title = items.pop(0)[1]
        levels.remove(1)
    depth_of = {level: depth for depth, level in enumerate(sorted(set(levels)), start=1)}

    texts: dict[int, list[str]] = {id(root): []}
    stack: list[tuple[int, Node]] = [(0, root)]
    for level, text in items:
        if not level:
            texts[id(stack[-1][1])].append(text)
            continue
        depth = depth_of[level]
        while stack[-1][0] >= depth:
            stack.pop()
        node = Node(title=text)
        stack[-1][1].children.append(node)
        stack.append((depth, node))
        texts[id(node)] = []

    for node in root.walk():
        node.text = "\n\n".join(texts[id(node)])
    assign_ids(root)
    return DocumentTree(
        doc_id=doc_id, title=root.title, source=source, source_type="html", root=root
    )


def _collect(element: Tag, items: list[Item], buffer: list[str]) -> None:
    for child in element.children:
        if isinstance(child, NavigableString):
            if type(child) is NavigableString:  # skips comments, CDATA, doctype
                buffer.append(str(child))
        elif child.name in _HEADINGS:
            _flush(items, buffer)
            title = _clean(child.get_text(" "))
            if title:
                items.append((int(child.name[1]), title))
        elif child.name == "br":
            buffer.append("\n")
        elif child.name in _BLOCKS:
            _flush(items, buffer)
            _collect(child, items, buffer)
            _flush(items, buffer)
        else:
            _collect(child, items, buffer)


def _flush(items: list[Item], buffer: list[str]) -> None:
    lines = (_clean(line) for line in "".join(buffer).split("\n"))
    text = "\n".join(line for line in lines if line)
    if text:
        items.append((0, text))
    buffer.clear()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "document"
