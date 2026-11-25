"""Command-line interface for RegTrace."""

from __future__ import annotations

import re
import time
from enum import StrEnum
from pathlib import Path

import httpx
import typer
from pydantic import BaseModel

from regtrace import __version__
from regtrace.config import load_settings
from regtrace.evidence import Report, Status, check_policy
from regtrace.llm import LLMConnectionError, LLMError, create_client
from regtrace.parsing import fetch_html, parse_html, parse_html_file, parse_pdf
from regtrace.regulations import LinkedObligation, link_pack, load_pack
from regtrace.tree import DocumentTree, Node, summarize_tree
from regtrace.verify import verify_report

DEFAULT_INDEX_DIR = Path("data") / "index"
DEFAULT_PACK = Path("packs") / "gdpr"
DEFAULT_RESULTS_DIR = Path("data") / "results"

app = typer.Typer(
    name="regtrace",
    help="Chunkless RAG for regulatory compliance gap analysis.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"regtrace {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """RegTrace command-line interface."""


@app.command()
def config() -> None:
    """Show the active LLM settings (from environment / .env)."""
    settings = load_settings()
    typer.echo(f"LLM host:     {settings.llm_host}")
    typer.echo(f"LLM model:    {settings.llm_model}")
    typer.echo(f"Context size: {settings.llm_num_ctx}")


class _Ping(BaseModel):
    reply: str


@app.command("llm-check")
def llm_check() -> None:
    """Send one small structured prompt to the LLM and report the reply and latency."""
    client = create_client()
    typer.echo(f"Checking {client.model} at {client.host} ...")

    start = time.perf_counter()
    try:
        result = client.generate_structured(
            'Reply with a JSON object whose "reply" field is a one-sentence greeting.',
            _Ping,
        )
    except LLMError as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    elapsed = time.perf_counter() - start

    typer.secho("OK", fg=typer.colors.GREEN)
    typer.echo(f"Reply:   {result.reply}")
    typer.echo(f"Latency: {elapsed:.1f}s")


class HeadingStrategy(StrEnum):
    auto = "auto"
    bookmarks = "bookmarks"
    legal = "legal"
    fonts = "fonts"


@app.command("build-index")
def build_index(
    source: str = typer.Argument(..., help="PDF file, HTML file or http(s) URL to index."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Where to write the JSON index [default: data/index/<doc>.json]."
    ),
    strategy: HeadingStrategy = typer.Option(
        HeadingStrategy.auto, help="How to find headings in a PDF."
    ),
    doc_id: str | None = typer.Option(None, "--doc-id", help="Document id [default: from name]."),
    summarize: bool = typer.Option(
        False, "--summarize/--no-summarize", help="Add an LLM summary to every section."
    ),
) -> None:
    """Parse a document into a section tree, print its outline and save it as JSON."""
    try:
        tree = _parse(source, strategy, doc_id)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    sections = sum(1 for _ in tree.walk()) - 1
    typer.echo(f"Title:    {tree.title}")
    if tree.source_type == "pdf":
        typer.echo(f"Pages:    {tree.root.page_end}")
    typer.echo(f"Sections: {sections}")
    typer.echo("")

    if summarize:
        _summarize(tree)
    typer.echo(tree.outline() if sections else "(no headings found; all text is in the root)")

    out = out or DEFAULT_INDEX_DIR / f"{tree.doc_id}.json"
    tree.save(out)
    typer.echo("")
    typer.secho(f"Saved index to {out}", fg=typer.colors.GREEN)


def _parse(source: str, strategy: HeadingStrategy, doc_id: str | None) -> DocumentTree:
    if source.startswith(("http://", "https://")):
        name = doc_id or _url_slug(source)
        return parse_html(fetch_html(source), source=source, doc_id=name)
    path = Path(source)
    if path.suffix.lower() in (".html", ".htm"):
        return parse_html_file(path, doc_id=doc_id)
    return parse_pdf(path, doc_id=doc_id, strategy=strategy.value)


def _url_slug(url: str) -> str:
    host_and_path = url.split("://", 1)[1].split("?")[0].split("#")[0]
    return re.sub(r"[^a-z0-9]+", "-", host_and_path.lower().removeprefix("www.")).strip("-")


def _summarize(tree: DocumentTree) -> None:
    """Run the summarizer with progress output; exit with code 1 if the LLM is unreachable."""
    client = create_client()
    typer.echo(f"Summarizing with {client.model} ...")

    def progress(done: int, total: int, node: Node) -> None:
        label = "(document)" if node is tree.root else f"{node.id} {node.short_title}"
        typer.echo(f"  [{done}/{total}] {label}")

    start = time.perf_counter()
    try:
        stats = summarize_tree(tree, client, on_progress=progress)
    except LLMConnectionError as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    elapsed = time.perf_counter() - start

    typer.echo(
        f"Summarized {stats.summarized}, skipped {stats.skipped} empty, "
        f"failed {len(stats.failed)} in {elapsed:.1f}s"
    )
    if stats.failed:
        typer.secho(f"No summary for: {', '.join(stats.failed)}", fg=typer.colors.YELLOW)
    typer.echo("")


@app.command("check-pack")
def check_pack(
    pack_dir: Path = typer.Argument(DEFAULT_PACK, help="Regulation pack folder."),
    regulation: Path | None = typer.Option(
        None, "--regulation", "-r", help="Regulation index JSON (default: from pack.yaml)."
    ),
    show: str | None = typer.Option(None, "--show", help="Print one obligation in full."),
) -> None:
    """Validate a regulation pack and link its obligations to the regulation text."""
    try:
        pack = load_pack(pack_dir)
        index = regulation or Path(pack.index)
        tree = DocumentTree.load(index)
    except (OSError, ValueError) as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    result = link_pack(pack, tree)
    if show:
        linked = next((item for item in result.linked if item.obligation.id == show), None)
        if linked is None:
            typer.secho(f"FAILED: no linked obligation {show!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        _print_obligation(linked)
        return

    conditional = sum(1 for o in pack.obligations if o.conditional)
    typer.echo(f"Pack:        {pack.name} (v{pack.version})")
    typer.echo(f"Regulation:  {index}")
    typer.echo(f"Definitions: {len(result.definitions)} from Article {pack.definitions_article}")
    typer.echo(f"Obligations: {len(pack.obligations)} ({conditional} conditional)")
    typer.echo("")
    width = max((len(o.id) for o in pack.obligations), default=2)
    typer.echo(f"{'ID':<{width}}  {'Ref':<9} {'Node':<8} {'If':<3} Terms / cross-references")
    for item in result.linked:
        o = item.obligation
        terms = ", ".join(d.term for d in item.definitions) or "-"
        refs = f"  -> Art. {', '.join(item.cross_refs)}" if item.cross_refs else ""
        flag = "yes" if o.conditional else ""
        typer.echo(f"{o.id:<{width}}  {o.ref:<9} {item.node_id:<8} {flag:<3} {terms}{refs}")

    typer.echo("")
    if result.errors:
        for error in result.errors:
            typer.secho(f"ERROR: {error}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(f"OK: all {len(result.linked)} obligations linked", fg=typer.colors.GREEN)


def _print_obligation(item: LinkedObligation) -> None:
    o = item.obligation
    typer.echo(f"{o.id}  (Art. {o.ref}, node {item.node_id})")
    typer.echo(f"{o.title}")
    typer.echo("")
    for label, value in [
        ("Who", o.who),
        ("What", o.what),
        ("When", o.when),
        ("Condition", o.condition or "none, always applies"),
        ("Evidence", o.evidence or "-"),
        ("Related", ", ".join(o.related) or "-"),
    ]:
        typer.echo(f"{label + ':':<11}{value}")
    typer.echo("")
    typer.echo("Regulation text:")
    typer.echo(f"  {item.source_text}")
    if item.definitions:
        typer.echo("")
        typer.echo("Definitions:")
        for definition in item.definitions:
            typer.echo(f"  Art. {definition.ref} {definition.text}")
    if item.cross_refs:
        typer.echo("")
        typer.echo(f"Cross-references: Art. {', '.join(item.cross_refs)}")


@app.command()
def check(
    policy_index: Path = typer.Argument(..., help="Policy index JSON (from build-index)."),
    pack_dir: Path = typer.Option(DEFAULT_PACK, "--pack", "-p", help="Regulation pack folder."),
    regulation: Path | None = typer.Option(
        None, "--regulation", "-r", help="Regulation index JSON (default: from pack.yaml)."
    ),
    only: list[str] | None = typer.Option(
        None, "--only", help="Check only this obligation id (repeatable)."
    ),
    assume: list[str] | None = typer.Option(
        None, "--assume", "-a", help="Answer a condition: ID=yes or ID=no (repeatable)."
    ),
    model: str | None = typer.Option(None, "--model", "-m", help="Override LLM_MODEL."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Report JSON (default: data/results/<policy>.<pack>.json)."
    ),
) -> None:
    """Check a policy against every obligation of a pack and print the compliance matrix."""
    try:
        policy = DocumentTree.load(policy_index)
        pack = load_pack(pack_dir)
        regulation_tree = DocumentTree.load(regulation or Path(pack.index))
    except (OSError, ValueError) as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    links = link_pack(pack, regulation_tree)
    if not links.ok:
        typer.secho("FAILED: the pack does not link, run check-pack", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    unknown = sorted(set(only or []) - {o.id for o in pack.obligations})
    if unknown:
        typer.secho(f"FAILED: unknown obligation {', '.join(unknown)}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    try:
        answers = _parse_assumptions(
            assume or [], {o.id for o in pack.obligations if o.conditional}
        )
    except ValueError as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    client = create_client(model=model)
    typer.echo(f"Checking {policy.title} against {pack.name} with {client.model} ...")

    def progress(done: int, total: int, item: LinkedObligation) -> None:
        typer.echo(f"  [{done}/{total}] {item.obligation.id}")

    try:
        report = check_policy(
            policy,
            links,
            client,
            regulation=regulation_tree,
            only=only,
            assume=answers,
            on_progress=progress,
        )
    except LLMConnectionError as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    verify_report(report, policy)
    typer.echo("")
    print_matrix(report)
    out = out or DEFAULT_RESULTS_DIR / f"{policy.doc_id}.{pack.id}.json"
    report.save(out)
    typer.echo("")
    typer.secho(f"Saved report to {out}", fg=typer.colors.GREEN)


def _parse_assumptions(values: list[str], conditional: set[str]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for value in values:
        obligation_id, _, answer = value.partition("=")
        obligation_id, answer = obligation_id.strip(), answer.strip().lower()
        if answer not in ("yes", "no"):
            raise ValueError(f"--assume {value!r}: expected ID=yes or ID=no")
        if obligation_id not in conditional:
            raise ValueError(f"--assume {value!r}: {obligation_id} is not a conditional obligation")
        answers[obligation_id] = answer
    return answers


@app.command()
def verify(
    report_path: Path = typer.Argument(..., help="Report JSON (from check)."),
    policy_index: Path | None = typer.Option(
        None, "--policy", help="Policy index JSON (default: data/index/<policy>.json)."
    ),
    pack_dir: Path = typer.Option(DEFAULT_PACK, "--pack", "-p", help="Regulation pack folder."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Where to save [default: in place]."),
) -> None:
    """Check the quotes of a saved report against the policy text, without the LLM."""
    try:
        report = Report.load(report_path)
        policy = DocumentTree.load(policy_index or DEFAULT_INDEX_DIR / f"{report.policy_id}.json")
        pack = load_pack(pack_dir)
    except (OSError, ValueError) as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    conditions = {o.id: o.condition for o in pack.obligations}
    for finding in report.findings:
        finding.condition = finding.condition or conditions.get(finding.obligation_id)
    verify_report(report, policy)
    print_matrix(report)
    out = out or report_path
    report.save(out)
    typer.echo("")
    typer.secho(f"Saved report to {out}", fg=typer.colors.GREEN)


_STATUS_COLORS = {
    "compliant": typer.colors.GREEN,
    "partial": typer.colors.YELLOW,
    "gap": typer.colors.RED,
    "not_addressed": typer.colors.RED,
    "depends": typer.colors.CYAN,
}


_CONFIDENCE_COLORS = {"high": typer.colors.GREEN, "medium": typer.colors.YELLOW}


def print_matrix(report: Report) -> None:
    width = max((len(f.obligation_id) for f in report.findings), default=2)
    typer.echo(
        f"{'Obligation':<{width}}  {'Ref':<9} {'Status':<14} {'Conf':<7} {'Quotes':<7} "
        f"{'Sections':<12} Explanation"
    )
    for f in report.findings:
        status = f.status.value if f.status else "error"
        confidence = f.confidence or "-"
        quotes = f"{sum(q.verified for q in f.quotes)}/{len(f.quotes)}" if f.quotes else "-"
        sections = ",".join(f.sections_read) or "-"
        if len(sections) > 12:
            sections = sections[:11] + "+"
        note = f.error or f.explanation
        note = note if len(note) <= 70 else note[:67] + "..."
        typer.echo(f"{f.obligation_id:<{width}}  {f.ref:<9} ", nl=False)
        typer.secho(f"{status:<14}", fg=_STATUS_COLORS.get(status, typer.colors.MAGENTA), nl=False)
        typer.secho(
            f" {confidence:<7}", fg=_CONFIDENCE_COLORS.get(confidence, typer.colors.RED), nl=False
        )
        typer.echo(f" {quotes:<7} {sections:<12} {note}")

    counts = report.counts()
    summary = ", ".join(f"{counts[k]} {k}" for k in [*_STATUS_COLORS, "error"] if k in counts)
    calls = sum(f.llm_calls for f in report.findings)
    verified, total = report.quote_counts()
    typer.echo("")
    typer.echo(f"{summary}  ({calls} LLM calls, {report.seconds:.0f}s)")
    typer.echo(f"Quotes verified: {verified}/{total}")
    low = sum(f.confidence == "low" for f in report.findings)
    if low:
        typer.secho(f"Low confidence: {low} finding(s), review these first", fg=typer.colors.RED)
    for f in report.findings:
        notes = f.flags + f.warnings
        if notes:
            typer.secho(f"  {f.obligation_id}: {'; '.join(notes)}", fg=typer.colors.YELLOW)

    open_questions = [f for f in report.findings if f.status == Status.depends]
    if open_questions:
        typer.echo("")
        typer.echo("Open questions (the policy does not say; answer with --assume ID=yes|no):")
        for f in open_questions:
            typer.echo(f"  {f.obligation_id}: {f.condition}")


if __name__ == "__main__":
    app()
