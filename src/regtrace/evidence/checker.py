"""Run every obligation of a pack against one policy and collect the findings."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from regtrace.evidence.judge import JudgeReply, judge
from regtrace.evidence.models import Finding, Quote, Report, Status
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
) -> Finding:
    o = item.obligation
    finding = Finding(obligation_id=o.id, ref=o.ref, title=o.title)
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

    status = _apply_condition(item, reply)
    finding.status = status
    finding.sections_read = read
    finding.explanation = reply.explanation.strip()
    if status != reply.status:
        finding.warnings.append(f"status {reply.status.value} -> {status.value} by condition")
    finding.fix = "" if status == Status.compliant else reply.fix.strip()
    readable = {n.id for node_id in read for n in policy.get(node_id).walk()}
    for quote in reply.quotes[:3]:
        section_id = quote.section_id.strip().removeprefix("section").strip()
        if section_id in readable and quote.text.strip():
            finding.quotes.append(Quote(section_id=section_id, text=quote.text.strip()))
        else:
            finding.warnings.append(f"quote from a section that was not read: {section_id!r}")
    if status in (Status.compliant, Status.partial) and not finding.quotes:
        finding.warnings.append(f"status {status.value} without a supporting quote")
    if status not in (Status.compliant, Status.depends) and not finding.fix:
        finding.warnings.append("no suggested fix")
    finding.seconds = round(time.perf_counter() - start, 1)
    return finding


def _apply_condition(item: LinkedObligation, reply: JudgeReply) -> Status:
    if not item.obligation.conditional:
        return reply.status
    if reply.condition_met == "no":
        return Status.compliant
    if reply.condition_met == "unknown" and reply.status in (Status.gap, Status.not_addressed):
        return Status.depends
    return reply.status


def check_policy(
    policy: DocumentTree,
    links: LinkResult,
    client: LLMClient,
    *,
    regulation: DocumentTree | None = None,
    only: list[str] | None = None,
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
    )
    start = time.perf_counter()
    for done, item in enumerate(items, start=1):
        if on_progress is not None:
            on_progress(done, len(items), item)
        report.findings.append(check_obligation(policy, item, client, regulation=regulation))
    report.seconds = round(time.perf_counter() - start, 1)
    return report
