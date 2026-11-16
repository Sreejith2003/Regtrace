# RegTrace

[![CI](https://github.com/Sreejith2003/Regtrace/actions/workflows/ci.yml/badge.svg)](https://github.com/Sreejith2003/Regtrace/actions/workflows/ci.yml)

**Chunkless RAG for regulatory compliance gap analysis.**

RegTrace checks a company's policy documents against a regulation and reports
where the policy falls short: which obligation, what the policy says (quoted
verbatim), whether it is compliant, and how to fix it.

> **Status:** early development. Only setup and configuration work so far.

> **Disclaimer:** RegTrace is meant to assist compliance analysts. It is **not
> legal advice**, and its output must be reviewed by a qualified person.

## Scope

- **MVP:** website privacy policies vs **GDPR Articles 12–14** (transparency
  obligations), using definitions from **Article 4**.
- **Later:** data subject rights (Arts. 15–22), breach notification
  (Arts. 33–34), and more regulation packs (India DPDP Act, EU AI Act).

## How it works

Instead of splitting documents into fixed-size chunks and searching a vector
database, RegTrace keeps each document's structure
([ADR 0002](docs/decisions/0002-chunkless-tree-retrieval.md)):

1. **Index:** parse each document into a section tree with a short LLM summary
   per node.
2. **Obligations:** a regulation pack defines structured obligations
   (who / what / when / conditions / article reference).
3. **Evidence finding:** for each obligation, the LLM navigates the policy tree
   the way an analyst skims a table of contents.
4. **Context expansion:** defined terms and cross-referenced articles are
   pulled in automatically.
5. **Judgment:** `compliant`, `partial`, `gap`, `not_addressed` or `depends`,
   with an explanation and a suggested fix.
6. **Verification:** every quoted clause must appear verbatim in the source.
7. **Output:** a compliance matrix and a follow-up chat.

All models run locally through [Ollama](https://ollama.com) (default:
`qwen2.5:7b`), so no document leaves your machine.

## Roadmap

- [x] Project setup (packaging, CI, design notes)
- [ ] Parse documents into section trees
- [ ] GDPR Articles 12–14 obligations pack
- [ ] Evidence finding and compliance judgment
- [ ] Quote verification
- [ ] Evaluation vs a chunked-RAG baseline
- [ ] Compliance report and follow-up chat

The headline result will be a comparison of chunkless vs chunked RAG on
planted-gap recall, false positives, citation correctness, latency and cost.

## Getting started (Windows)

Requirements: Python 3.11+ and [Ollama](https://ollama.com/download).

```powershell
git clone https://github.com/Sreejith2003/Regtrace.git
cd Regtrace

# Create and activate a virtual environment
python -m venv rag
.\rag\Scripts\Activate.ps1        # cmd: rag\Scripts\activate.bat

# Install RegTrace with development tools
pip install -e ".[dev]"

# Pull the local model and configure
ollama pull qwen2.5:7b
copy .env.example .env

# Check the setup
regtrace --version
regtrace config
```

On macOS/Linux, activate with `source rag/bin/activate` and use `cp` instead of
`copy`.

## Development

```powershell
pytest              # run tests
ruff check .        # lint
ruff format .       # format
```

Design decisions are recorded in [`docs/decisions/`](docs/decisions/).

## Data policy

Third-party policy text is never committed. The repository holds URLs and
download scripts; documents are stored in `data/`, which is gitignored.
Confidential company documents are never used.

## Known limitations

These will be measured and expanded as the project matures:

- Scanned (image-only) PDFs are not supported. There is no OCR.
- Tree navigation makes several LLM calls per obligation, so a full run is
  slower than a single vector lookup.
- Designed for analysing a few long documents in depth, not for searching
  thousands of documents.

## License

[MIT](LICENSE)
