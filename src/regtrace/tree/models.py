"""Section tree: the structure every RegTrace document is indexed into."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ROOT_ID = "0"


class NodeNotFoundError(LookupError):
    """Raised when a node id does not exist in a document tree."""


class Node(BaseModel):
    """One section of a document (chapter, article, paragraph, subsection, ...)."""

    id: str = ""
    title: str
    level: int = Field(default=0, ge=0)
    text: str = ""  # this node's own body text only, not its children's
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    summary: str | None = None
    children: list[Node] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_page_range(self) -> Node:
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must not be before page_start")
        return self

    def walk(self) -> Iterator[Node]:
        """Yield this node and all its descendants depth-first, in reading order."""
        yield self
        for child in self.children:
            yield from child.walk()


def assign_ids(root: Node) -> None:
    """Number a tree path-style and set levels: root "0", children "1", "2", then "2.1", ...

    Parsers only build the nesting; this gives every node a stable, short id.
    """
    root.id = ROOT_ID
    root.level = 0
    _number_children(root, prefix="")


def _number_children(node: Node, prefix: str) -> None:
    for index, child in enumerate(node.children, start=1):
        child.id = f"{prefix}{index}"
        child.level = node.level + 1
        _number_children(child, prefix=f"{child.id}.")


class DocumentTree(BaseModel):
    """A whole document as a section tree, plus where it came from."""

    doc_id: str = Field(min_length=1)
    title: str
    source: str  # file path or URL
    source_type: Literal["pdf", "html"]
    root: Node

    def walk(self) -> Iterator[Node]:
        """Yield every node depth-first, in reading order."""
        return self.root.walk()

    def get(self, node_id: str) -> Node:
        """Return the node with `node_id`, or raise `NodeNotFoundError`."""
        for node in self.walk():
            if node.id == node_id:
                return node
        raise NodeNotFoundError(f"No node with id {node_id!r} in document {self.doc_id!r}")

    def full_text(self, node_id: str = ROOT_ID) -> str:
        """Return a node's heading and text plus those of all its descendants."""
        parts: list[str] = []
        for node in self.get(node_id).walk():
            if node.title:
                parts.append(node.title)
            if node.text:
                parts.append(node.text)
        return "\n\n".join(parts)

    def outline(self, max_depth: int | None = None, with_summaries: bool = True) -> str:
        """Return an indented table of contents, the view the LLM navigates with.

        Example line: ``  2.1  Contact data: Lists the contact details collected.``
        """
        lines: list[str] = []
        for node in self.walk():
            if node is self.root:
                continue
            if max_depth is not None and node.level > max_depth:
                continue
            indent = "  " * (node.level - 1)
            line = f"{indent}{node.id}  {node.title}"
            if with_summaries and node.summary:
                line += f": {node.summary}"
            lines.append(line)
        return "\n".join(lines)

    def save(self, path: str | Path) -> None:
        """Write the tree as JSON (UTF-8), creating parent folders if needed."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> DocumentTree:
        """Read a tree previously written by `save`."""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
