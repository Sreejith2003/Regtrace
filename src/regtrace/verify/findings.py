"""Check every quote of a finding against the policy and rate how far to trust it."""

from __future__ import annotations

from regtrace.evidence.models import Confidence, Finding, Match, Report, Status
from regtrace.tree import DocumentTree, Node, NodeNotFoundError
from regtrace.verify.quotes import locate


def verify_finding(finding: Finding, policy: DocumentTree) -> Finding:
    finding.flags = []
    readable = {n.id for i in finding.sections_read for n in _subtree(policy, i)}
    for quote in finding.quotes:
        found = locate(policy, quote.text, quote.section_id, prefer=finding.sections_read)
        quote.match = found.match
        quote.source_text = found.text
        short = _short(quote.text)
        if found.match == Match.not_found:
            finding.flags.append(f"quote not found in the policy: {short}")
            continue
        if found.section_id != quote.section_id:
            finding.flags.append(f"quote is in section {found.section_id}, not {quote.section_id}")
            quote.section_id = found.section_id
        if readable and found.section_id not in readable:
            finding.flags.append(f"quote comes from section {found.section_id}, which was not read")
        if found.match == Match.fuzzy:
            finding.flags.append(f"quote only loosely matches the text ({found.coverage:.0%})")
        elif found.match == Match.spliced:
            finding.flags.append("quote joins separate passages")
    finding.confidence = rate(finding)
    return finding


def verify_report(report: Report, policy: DocumentTree) -> Report:
    for finding in report.findings:
        verify_finding(finding, policy)
    return report


def rate(finding: Finding) -> Confidence:
    if finding.error or finding.status is None:
        return "low"
    if any(q.match == Match.not_found for q in finding.quotes):
        return "low"
    supported = finding.assumed or any(q.verified for q in finding.quotes)
    if finding.status in (Status.compliant, Status.partial) and not supported:
        return "low"
    if finding.status == Status.depends or finding.flags or finding.warnings:
        return "medium"
    return "high"


def _subtree(policy: DocumentTree, node_id: str) -> list[Node]:
    try:
        return list(policy.get(node_id).walk())
    except NodeNotFoundError:
        return []


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return repr(text if len(text) <= limit else text[:limit] + "...")
