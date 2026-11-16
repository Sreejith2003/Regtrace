from typer.testing import CliRunner

from regtrace import __version__
from regtrace.cli import app

runner = CliRunner()


def test_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_command_shows_settings(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model:1b")

    result = runner.invoke(app, ["config"])

    assert result.exit_code == 0
    assert "test-model:1b" in result.output
