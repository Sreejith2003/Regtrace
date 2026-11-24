import httpx
import pymupdf
from typer.testing import CliRunner

from regtrace import __version__
from regtrace.cli import app
from regtrace.llm import LLMConnectionError
from regtrace.tree import DocumentTree

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


class _FakeClient:
    model = "fake-model"
    host = "http://fake:11434"

    def __init__(self, error=None):
        self.error = error

    def generate_structured(self, prompt, schema, *, system=None):
        if self.error:
            raise self.error
        return schema(reply="Hello there!")


def test_llm_check_reports_reply(monkeypatch):
    monkeypatch.setattr("regtrace.cli.create_client", lambda: _FakeClient())

    result = runner.invoke(app, ["llm-check"])

    assert result.exit_code == 0
    assert "OK" in result.output
    assert "Hello there!" in result.output


def test_llm_check_fails_cleanly_when_llm_unreachable(monkeypatch):
    error = LLMConnectionError("Could not reach Ollama")
    monkeypatch.setattr("regtrace.cli.create_client", lambda: _FakeClient(error))

    result = runner.invoke(app, ["llm-check"])

    assert result.exit_code == 1


def _make_policy_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    body = "This paragraph is ordinary body text that explains the section in detail."
    y = 100
    for text, size in [("Who we are", 16), (body, 11), ("Your rights", 16), (body, 11)]:
        page.insert_text((72, y), text, fontsize=size)
        y += size + 10
    doc.save(path)
    doc.close()
    return path


def test_build_index_prints_outline_and_saves_json(tmp_path):
    pdf = _make_policy_pdf(tmp_path / "policy.pdf")
    out = tmp_path / "policy.json"

    result = runner.invoke(app, ["build-index", str(pdf), "--out", str(out)])

    assert result.exit_code == 0
    assert "Sections: 2" in result.output
    assert "2  Your rights" in result.output
    assert DocumentTree.load(out).get("1").title == "Who we are"


def test_build_index_defaults_to_data_index_folder(tmp_path, monkeypatch):
    pdf = _make_policy_pdf(tmp_path / "My Policy.pdf")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build-index", str(pdf)])

    assert result.exit_code == 0
    assert (tmp_path / "data" / "index" / "my-policy.json").is_file()


class _SummaryClient:
    model = "fake-model"

    def generate_structured(self, prompt, schema, *, system=None):
        return schema(summary="Fake summary.")


def test_build_index_summarize_adds_summaries(tmp_path, monkeypatch):
    monkeypatch.setattr("regtrace.cli.create_client", lambda: _SummaryClient())
    pdf = _make_policy_pdf(tmp_path / "policy.pdf")
    out = tmp_path / "policy.json"

    result = runner.invoke(app, ["build-index", str(pdf), "--out", str(out), "--summarize"])

    assert result.exit_code == 0
    assert "2  Your rights: Fake summary." in result.output
    assert DocumentTree.load(out).get("1").summary == "Fake summary."


def test_build_index_without_summarize_makes_no_llm_calls(tmp_path, monkeypatch):
    def fail():
        raise AssertionError("LLM client should not be created")

    monkeypatch.setattr("regtrace.cli.create_client", fail)
    pdf = _make_policy_pdf(tmp_path / "policy.pdf")

    result = runner.invoke(app, ["build-index", str(pdf), "--out", str(tmp_path / "p.json")])

    assert result.exit_code == 0


def test_build_index_summarize_fails_cleanly_when_llm_unreachable(tmp_path, monkeypatch):
    error = LLMConnectionError("Could not reach Ollama")
    monkeypatch.setattr("regtrace.cli.create_client", lambda: _FakeClient(error))
    pdf = _make_policy_pdf(tmp_path / "policy.pdf")
    out = tmp_path / "policy.json"

    result = runner.invoke(app, ["build-index", str(pdf), "--out", str(out), "--summarize"])

    assert result.exit_code == 1
    assert not out.exists()


def test_build_index_rejects_missing_file(tmp_path):
    result = runner.invoke(app, ["build-index", str(tmp_path / "missing.pdf")])

    assert result.exit_code != 0


POLICY_HTML = "<h1>Policy</h1><h2>Who we are</h2><p>Acme Ltd.</p><h2>Your rights</h2><p>Ask.</p>"


def test_build_index_reads_html_file(tmp_path):
    page = tmp_path / "policy.html"
    page.write_text(POLICY_HTML, encoding="utf-8")
    out = tmp_path / "policy.json"

    result = runner.invoke(app, ["build-index", str(page), "--out", str(out)])

    assert result.exit_code == 0
    assert "Sections: 2" in result.output
    assert "Pages:" not in result.output
    assert DocumentTree.load(out).source_type == "html"


def test_build_index_fetches_url(tmp_path, monkeypatch):
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return POLICY_HTML

    monkeypatch.setattr("regtrace.cli.fetch_html", fake_fetch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build-index", "https://www.acme.example/legal/privacy?lang=en"])

    assert result.exit_code == 0
    assert urls == ["https://www.acme.example/legal/privacy?lang=en"]
    tree = DocumentTree.load(tmp_path / "data" / "index" / "acme-example-legal-privacy.json")
    assert tree.source == "https://www.acme.example/legal/privacy?lang=en"


def test_build_index_doc_id_option(tmp_path, monkeypatch):
    page = tmp_path / "policy.html"
    page.write_text(POLICY_HTML, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["build-index", str(page), "--doc-id", "acme"])

    assert result.exit_code == 0
    assert (tmp_path / "data" / "index" / "acme.json").is_file()


def test_build_index_fails_cleanly_when_url_unreachable(tmp_path, monkeypatch):
    def fake_fetch(url):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("regtrace.cli.fetch_html", fake_fetch)

    result = runner.invoke(app, ["build-index", "https://acme.example/privacy"])

    assert result.exit_code == 1
    assert "FAILED" in result.output
