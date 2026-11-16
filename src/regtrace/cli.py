"""Command-line interface for RegTrace."""

from __future__ import annotations

import typer

from regtrace import __version__
from regtrace.config import load_settings

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


if __name__ == "__main__":
    app()
