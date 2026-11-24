from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class Status(StrEnum):
    compliant = "compliant"
    partial = "partial"
    gap = "gap"
    not_addressed = "not_addressed"
    depends = "depends"


class Quote(BaseModel):
    section_id: str
    text: str


class Finding(BaseModel):
    obligation_id: str
    ref: str
    title: str
    status: Status | None = None
    quotes: list[Quote] = Field(default_factory=list)
    explanation: str = ""
    fix: str = ""
    sections_read: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    llm_calls: int = 0
    seconds: float = 0.0


class Report(BaseModel):
    policy_id: str
    policy_title: str
    policy_source: str
    pack_id: str
    model: str
    created: str
    seconds: float = 0.0
    findings: list[Finding] = Field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counter = Counter(f.status.value if f.status else "error" for f in self.findings)
        return dict(counter)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Report:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
