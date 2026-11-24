"""Decide whether the sections read satisfy one obligation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from regtrace.evidence.models import Status
from regtrace.llm import LLMClient
from regtrace.regulations import ArticleRef, LinkedObligation, find_article, point_text
from regtrace.tree import DocumentTree

DEFINITION_CHARS = 300
CROSS_REF_CHARS = 500
MAX_CROSS_REFS = 3

SYSTEM_PROMPT = """\
You are a careful data protection analyst. You check one GDPR requirement against excerpts \
of a company's privacy policy. Base your answer only on the excerpts. Quotes must be copied \
word for word from the excerpts, never paraphrased or invented. This assists a human \
reviewer and is not legal advice."""

STATUS_RULES = """\
Statuses:
- compliant: the excerpts clearly give everything the requirement asks for.
- partial: the excerpts address it, but something required is missing or too vague.
- gap: the policy covers the topic but leaves out or contradicts the core of the requirement.
- not_addressed: none of the excerpts deal with the requirement at all.
- depends: the requirement only applies under a condition, and the excerpts do not show \
whether that condition holds.
If the requirement is conditional and the excerpts show the condition does not hold, \
answer compliant and say why."""


class QuoteReply(BaseModel):
    section_id: str
    text: str


class JudgeReply(BaseModel):
    quotes: list[QuoteReply]
    explanation: str
    status: Status
    fix: str
    more_sections: list[str] = Field(default_factory=list)


def judge(
    item: LinkedObligation,
    evidence: str,
    client: LLMClient,
    *,
    regulation: DocumentTree | None = None,
    outline: str = "",
    allow_more: bool = True,
) -> JudgeReply:
    prompt = build_prompt(
        item, evidence, regulation=regulation, outline=outline, allow_more=allow_more
    )
    return client.generate_structured(prompt, JudgeReply, system=SYSTEM_PROMPT)


def build_prompt(
    item: LinkedObligation,
    evidence: str,
    *,
    regulation: DocumentTree | None = None,
    outline: str = "",
    allow_more: bool = True,
) -> str:
    o = item.obligation
    lines = [
        f"Requirement: {o.title} (GDPR Art. {o.ref})",
        f"Who: {o.who}",
        f"What the policy must say: {o.what}",
        f"When: {o.when}",
        f"Condition: {o.condition}" if o.condition else "Condition: none, it always applies.",
        "",
        "Regulation text:",
        item.source_text,
    ]
    if item.definitions:
        lines += ["", "Definitions (GDPR Art. 4):"]
        lines += [f"- {_short(d.text, DEFINITION_CHARS)}" for d in item.definitions]
    referenced = cross_ref_texts(item, regulation) if regulation else []
    if referenced:
        lines += ["", "Referenced provisions:"]
        lines += [f"- Art. {ref}: {text}" for ref, text in referenced]
    lines += ["", "Policy excerpts:", evidence or "(no excerpts)", "", STATUS_RULES, ""]
    if allow_more and outline:
        lines += [
            "If the excerpts are not enough to decide, list up to 3 other section ids from "
            "this outline in more_sections:",
            outline,
            "",
        ]
    lines.append(
        "Work in this order. quotes: copy the 1-3 most relevant sentences exactly as written, "
        "with their section_id; leave empty only if no excerpt deals with the requirement. "
        "explanation: 2-3 sentences comparing the quotes with the requirement. status: one of "
        "the statuses above. fix: one concrete sentence the policy should add or change "
        "(required unless compliant)" + (", more_sections." if allow_more and outline else ".")
    )
    return "\n".join(lines)


def cross_ref_texts(item: LinkedObligation, regulation: DocumentTree) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for ref in item.cross_refs[:MAX_CROSS_REFS]:
        article_ref = ArticleRef.parse(ref)
        node = find_article(regulation, article_ref)
        if node is None:
            continue
        if article_ref.point:
            text = point_text(node.text, article_ref.point)
        elif article_ref.paragraph:
            text = node.text
        else:
            text = node.title
        if text:
            texts.append((ref, _short(text, CROSS_REF_CHARS)))
    return texts


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + " [...]"
