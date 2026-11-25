"""Run every obligation of a pack against one policy and collect the findings."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from regtrace.evidence.judge import judge
from regtrace.evidence.models import ConditionMet, Finding, Quote, Report, Status
from regtrace.evidence.navigator import (
    choose_sections,
    read_sections,
    titles_outline,
    valid_ids,
)
from regtrace.llm import LLMClient, LLMConnectionError, LLMError
from regtrace.regulations import LinkedObligation, LinkResult
from regtrace.tree import DocumentTree

MAX_ROUNDS = 2

ProgressCallback = Callable[[int, int, LinkedObligation], None]


def check_obligation(
    policy: DocumentTree,
    item: LinkedObligation,
    client: LLMClient,
    *,
    regulation: DocumentTree | None = None,
    assume: ConditionMet | None = None,
) -> Finding:
    o = item.obligation
    finding = Finding(obligation_id=o.id, ref=o.ref, title=o.title, condition=o.condition)
    if not o.conditional:
        assume = None
    if assume == "no":
        finding.status = Status.compliant
        finding.condition_met = "no"
        finding.assumed = True
        finding.explanation = "Does not apply: the condition was answered as not met."
        return finding

    start = time.perf_counter()
    try:
        choice = choose_sections(policy, item, client)
        finding.llm_calls += 1 if policy.root.children else 0
        read = choice.section_ids or [policy.root.id]
        outline = titles_outline(policy) if policy.root.children else ""
        for round_no in range(1, MAX_ROUNDS + 1):
            last = round_no == MAX_ROUNDS
            reply = judge(
                item,
                read_sections(policy, read),
                client,
                regulation=regulation,
                outline=outline,
                allow_more=not last,
            )
            finding.llm_calls += 1
            more = [i for i in valid_ids(policy, reply.more_sections, limit=3) if i not in read]
            if last or not more or reply.status == Status.compliant:
                break
            read += more
    except LLMConnectionError:
        raise
    except LLMError as exc:
        finding.error = str(exc)
        finding.seconds = round(time.perf_counter() - start, 1)
        return finding

    finding.sections_read = read
    finding.judged_status = reply.status
    finding.explanation = reply.explanation.strip()
    finding.quotes = [
        Quote(section_id=q.section_id.strip().removeprefix("section").strip(), text=q.text.strip())
        for q in reply.quotes[:3]
        if q.text.strip()
    ]
    if o.conditional:
        finding.condition_met = assume or reply.condition_met
        finding.assumed = assume is not None
    status = resolve_status(finding)
    finding.status = status
    if status != reply.status:
        finding.warnings.append(f"status {reply.status.value} -> {status.value} by condition")
    if status == Status.compliant:
        finding.fix = ""
    elif status == Status.depends:
        finding.fix = reply.fix.strip() or f"If this applies ({o.condition}), state: {o.what}"
    else:
        finding.fix = reply.fix.strip()
    if status in (Status.compliant, Status.partial) and not finding.quotes:
        finding.warnings.append(f"status {status.value} without a supporting quote")
    if status not in (Status.compliant, Status.depends) and not finding.fix:
        finding.warnings.append("no suggested fix")
    finding.seconds = round(time.perf_counter() - start, 1)
    return finding


def resolve_status(finding: Finding) -> Status:
    """Apply the condition in code; `depends` is only possible when the condition is unknown."""
    status = finding.judged_status
    if status is None:
        raise ValueError("finding has not been judged")
    met = finding.condition_met if finding.condition is not None else "yes"
    if met == "no":
        return Status.compliant
    if met == "unknown" and status in (Status.gap, Status.not_addressed, Status.depends):
        return Status.depends
    if status == Status.depends:
        return Status.partial if finding.quotes else Status.not_addressed
    return status


def check_policy(
    policy: DocumentTree,
    links: LinkResult,
    client: LLMClient,
    *,
    regulation: DocumentTree | None = None,
    only: list[str] | None = None,
    assume: dict[str, ConditionMet] | None = None,
    on_progress: ProgressCallback | None = None,
) -> Report:
    items = [i for i in links.linked if not only or i.obligation.id in only]
    report = Report(
        policy_id=policy.doc_id,
        policy_title=policy.title,
        policy_source=policy.source,
        pack_id=links.pack_id,
        model=getattr(client, "model", "unknown"),
        created=datetime.now(UTC).isoformat(timespec="seconds"),
        assumptions=dict(assume or {}),
    )
    start = time.perf_counter()
    for done, item in enumerate(items, start=1):
        if on_progress is not None:
            on_progress(done, len(items), item)
        answer = report.assumptions.get(item.obligation.id)
        report.findings.append(
            check_obligation(policy, item, client, regulation=regulation, assume=answer)
        )
    report.seconds = round(time.perf_counter() - start, 1)
    return report
