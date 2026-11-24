"""Connect pack obligations to the indexed regulation text."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from regtrace.regulations.models import ArticleRef, Definition, Obligation, Pack
from regtrace.tree import DocumentTree, Node

_DEFINITION = re.compile(r"\((\d+)\) ‘([^’]+)’((?: [\w ]{1,30}?)?) means:? (.*?)(?=\s\(\d+\) ‘|$)")
_QUOTED = re.compile(r"‘([^’]+)’")
_OTHER_ACT = r"(?! of (?:Directive|Regulation))"
_POINT_OF = re.compile(rf"point \(([a-z])\) of Article (\d+)\((\d+)\){_OTHER_ACT}")
_REF_LIST = r"\d+(?:\(\d+\))*(?:(?:, | or | and | to )(?:\d+|\(\d+\))(?:\(\d+\))*)*"
_ARTICLES = re.compile(rf"Articles? (?>({_REF_LIST})){_OTHER_ACT}")


class LinkedObligation(BaseModel):
    obligation: Obligation
    node_id: str
    source_text: str
    definitions: list[Definition] = Field(default_factory=list)
    cross_refs: list[str] = Field(default_factory=list)


class LinkResult(BaseModel):
    pack_id: str
    definitions: list[Definition]
    linked: list[LinkedObligation]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def link_pack(pack: Pack, regulation: DocumentTree) -> LinkResult:
    errors: list[str] = []
    definitions_node = find_article(regulation, ArticleRef(article=pack.definitions_article))
    definitions = extract_definitions(definitions_node) if definitions_node else []
    if not definitions:
        errors.append(f"No definitions found in Article {pack.definitions_article}")

    linked: list[LinkedObligation] = []
    for obligation in pack.obligations:
        ref = obligation.article_ref
        node = find_article(regulation, ref)
        if node is None:
            errors.append(f"{obligation.id}: Article {ref} not found in the regulation index")
            continue
        text = regulation.full_text(node.id) if ref.paragraph is None else _clean(node.text)
        if ref.point:
            text = point_text(node.text, ref.point)
            if not text:
                errors.append(f"{obligation.id}: point ({ref.point}) not found in Article {ref}")
                continue
        for related in obligation.related:
            if find_article(regulation, ArticleRef.parse(related)) is None:
                errors.append(f"{obligation.id}: related Article {related} not found")
        linked.append(
            LinkedObligation(
                obligation=obligation,
                node_id=node.id,
                source_text=text,
                definitions=terms_in(f"{text} {obligation.what}", definitions),
                cross_refs=[r for r in cross_refs(text) if r != str(ref)],
            )
        )
    return LinkResult(pack_id=pack.id, definitions=definitions, linked=linked, errors=errors)


def find_article(tree: DocumentTree, ref: ArticleRef) -> Node | None:
    article = re.compile(rf"Article {ref.article}(?:\s|$)")
    for node in tree.walk():
        if not article.match(node.title):
            continue
        if ref.paragraph is None:
            return node
        wanted = f"Article {ref.article}({ref.paragraph})"
        return next((child for child in node.children if child.title == wanted), None)
    return None


def point_text(paragraph_text: str, letter: str) -> str:
    match = re.search(
        rf"(?:^|\n)\({letter}\) (.*?)(?=\n\n\([a-z]\) |\Z)", paragraph_text, flags=re.S
    )
    return _clean(match[1]) if match else ""


def extract_definitions(article: Node) -> list[Definition]:
    """Definitions written as "(1) ‘term’ means ...", plus terms quoted inside them."""
    text = _clean(article.text)
    definitions: list[Definition] = []
    for number, term, qualifier, meaning in _DEFINITION.findall(text):
        ref = f"{_article_number(article)}({number})"
        full = f"‘{term}’{qualifier} means {meaning}"
        for name in [term, *_QUOTED.findall(meaning)]:
            definitions.append(Definition(term=name, ref=ref, text=full))
    return definitions


def terms_in(text: str, definitions: list[Definition]) -> list[Definition]:
    """Defined terms used in `text`; longer terms win ("personal data breach")."""
    found: list[Definition] = []
    remaining = text
    for definition in sorted(definitions, key=lambda d: len(d.term), reverse=True):
        pattern = rf"\b{re.escape(definition.term)}s?\b"
        if re.search(pattern, remaining, flags=re.I):
            found.append(definition)
            remaining = re.sub(pattern, " ", remaining, flags=re.I)
    return sorted(found, key=lambda d: _ref_key(d.ref))


def cross_refs(text: str) -> list[str]:
    refs: list[str] = []
    for letter, article, paragraph in _POINT_OF.findall(text):
        refs.append(f"{article}({paragraph})({letter})")
    for group in _ARTICLES.findall(_POINT_OF.sub(" ", text)):
        refs.extend(_expand(group))
    return list(dict.fromkeys(refs))


def _expand(group: str) -> list[str]:
    """Expand "15 to 17" to 15, 16, 17 and "22(1) and (4)" to 22(1), 22(4)."""
    refs: list[str] = []
    article = ""
    for part in re.split(r", | or | and ", group):
        if " to " in part:
            first, last = (re.match(r"\d+", side)[0] for side in part.split(" to "))
            refs.extend(str(n) for n in range(int(first), int(last) + 1))
            article = last
        elif part.startswith("("):
            refs.append(article + part)
        else:
            refs.append(part)
            article = re.match(r"\d+", part)[0]
    return refs


def _article_number(node: Node) -> str:
    match = re.match(r"Article (\d+)", node.title)
    return match[1] if match else ""


def _ref_key(ref: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", ref))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
