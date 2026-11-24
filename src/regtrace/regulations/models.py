"""Regulation packs: structured obligations a policy is checked against."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

_REF = re.compile(r"(\d+)(?:\((\d+)\))?(?:\(([a-z])\))?")


class ArticleRef(BaseModel):
    article: str
    paragraph: str | None = None
    point: str | None = None

    @classmethod
    def parse(cls, ref: str) -> ArticleRef:
        match = _REF.fullmatch(ref.strip())
        if match is None:
            raise ValueError(f"Not an article reference: {ref!r} (expected e.g. '13(1)(a)')")
        return cls(article=match[1], paragraph=match[2], point=match[3])

    def __str__(self) -> str:
        text = self.article
        if self.paragraph:
            text += f"({self.paragraph})"
        if self.point:
            text += f"({self.point})"
        return text


class Obligation(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    ref: str
    title: str
    who: str
    what: str
    when: str
    condition: str | None = None
    evidence: str = ""
    related: list[str] = Field(default_factory=list)

    @field_validator("ref")
    @classmethod
    def _valid_ref(cls, value: str) -> str:
        return str(ArticleRef.parse(value))

    @field_validator("related")
    @classmethod
    def _valid_related(cls, values: list[str]) -> list[str]:
        return [str(ArticleRef.parse(value)) for value in values]

    @property
    def article_ref(self) -> ArticleRef:
        return ArticleRef.parse(self.ref)

    @property
    def conditional(self) -> bool:
        return self.condition is not None


class Definition(BaseModel):
    term: str
    ref: str
    text: str


class Pack(BaseModel):
    id: str
    name: str
    regulation: str
    source_url: str = ""
    index: str
    definitions_article: str
    version: str = "0.1"
    obligations: list[Obligation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> Pack:
        seen: set[str] = set()
        for obligation in self.obligations:
            if obligation.id in seen:
                raise ValueError(f"Duplicate obligation id: {obligation.id}")
            seen.add(obligation.id)
        return self

    def get(self, obligation_id: str) -> Obligation:
        for obligation in self.obligations:
            if obligation.id == obligation_id:
                return obligation
        raise KeyError(f"No obligation {obligation_id!r} in pack {self.id!r}")
