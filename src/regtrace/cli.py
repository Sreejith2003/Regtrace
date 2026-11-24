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
from regtrace.llm import LLMConnectionError, LLMError, create_client
from regtrace.parsing import fetch_html, parse_html, parse_html_file, parse_pdf
from regtrace.tree import DocumentTree, Node, summarize_tree

DEFAULT_INDEX_DIR = Path("data") / "index"

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


if __name__ == "__main__":
    app()
