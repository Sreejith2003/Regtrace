# RegTrace

[![CI](https://github.com/Sreejith2003/Regtrace/actions/workflows/ci.yml/badge.svg)](https://github.com/Sreejith2003/Regtrace/actions/workflows/ci.yml)

**Chunkless RAG for regulatory compliance gap analysis.**

RegTrace checks a company's policy documents against a regulation and reports
where the policy falls short: which obligation, what the policy says (quoted
verbatim), whether it is compliant, and how to fix it.

> **Status:** early development (Phase 3 done). Policies (PDF, HTML or a URL)
> can be checked against the GDPR Arts. 12–14 obligations pack with
> `regtrace check`, giving a compliance matrix with quotes and fixes. Quote
> verification (Phase 4) and the evaluation against a chunked baseline
> (Phases 5–6) are next, so results are not yet measured.

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
- [x] Parse documents into section trees
  - [x] Tree model, LLM client, PDF parser (bookmarks / font sizes)
  - [x] Legal-text parser: chapters, sections, articles, paragraphs (GDPR)
  - [x] HTML parser and `build-index <url>` for real web privacy policies
  - [x] Bottom-up LLM summaries per section (`build-index --summarize`)
  - [x] Design note for summaries (ADR 0005)
- [x] GDPR Articles 12–14 obligations pack
  - [x] 19 obligations with conditions (`packs/gdpr/`, ADR 0004)
  - [x] Art. 4 definitions and cross-references linked (`check-pack`)
- [x] Evidence finding and compliance judgment (`regtrace check`, ADR 0006)
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
regtrace llm-check   # sends one small prompt to Ollama
```

On macOS/Linux, activate with `source rag/bin/activate` and use `cp` instead of
`copy`.

## Usage

### Sample policies

`scripts/make_sample_policies.py` generates three fictional privacy policies
with deliberately missing GDPR Art. 13 information ("planted gaps"), plus
`planted_gaps.json` listing what is missing in each:

```powershell
python scripts\make_sample_policies.py     # writes to data\samples\
```

### Real privacy policies

`scripts/policies.yaml` lists public privacy policies of EU/UK-facing
services (Spotify, BBC, IKEA UK, DuckDuckGo, Proton, Mozilla). Only the URLs
are committed. The script saves the pages to `data\raw\policies\` with a
`manifest.json` (URL, retrieval time, SHA-256), so you can tell when a policy
has changed:

```powershell
python scripts\download_policies.py                 # all policies
python scripts\download_policies.py --only spotify  # just one
regtrace build-index data\raw\policies\spotify.html
```

### Build an index

`build-index` parses a PDF, an HTML file or a web page into a section tree,
prints its outline and saves it as JSON (default: `data\index\<doc>.json`):

```powershell
regtrace build-index data\samples\brightleaf-coffee.pdf
regtrace build-index data\samples\brightleaf-coffee.pdf --summarize
regtrace build-index https://www.spotify.com/uk/legal/privacy-policy/ --doc-id spotify
regtrace build-index data\raw\policies\bbc.html
```

For HTML, `<h1>`–`<h6>` become the sections. Navigation, headers, footers,
scripts and other page chrome outside the main content are dropped. A single
`<h1>` at the top becomes the document title.

| Option | Meaning |
|---|---|
| `--out`, `-o` | Where to write the JSON index |
| `--doc-id` | Document id, used for the file name [default: from the file name or URL] |
| `--strategy` | How to find headings in a PDF: `auto` (default), `bookmarks`, `legal`, `fonts` |
| `--summarize` | Add a short LLM summary to every section (needs Ollama running) |

`auto` uses the PDF's bookmarks if it has any, then the `legal` layout if it
finds at least three `Article N` headings, and font sizes otherwise.

### Index the GDPR

Download the official GDPR PDF from
[EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32016R0679)
and save it as `data\raw\gdpr.pdf`, then:

```powershell
regtrace build-index data\raw\gdpr.pdf
```

The `legal` strategy finds `CHAPTER I`, `Section 1`, `Article 13` and numbered
paragraphs (`1.`, `2.`), each with its title. The recitals stay in the root.
Lettered points like `(a)` stay inside their paragraph's text:

```text
3  CHAPTER III Rights of the data subject
  3.1  Section 1 Transparency and modalities
    3.1.1  Article 12 Transparent information, communication and modalities for the exercise of the rights of the data subject
      3.1.1.1  Article 12(1)
  ...
  3.2  Section 2 Information and access to personal data
    3.2.1  Article 13 Information to be provided where personal data are collected from the data subject
```

Summaries are built **bottom-up**: each section is summarized from its own
text plus its subsections' summaries, ending with the whole document. They
describe what a section covers, never whether it is compliant, and are what
the evidence finder will read to decide which section to open. Example
output:

```text
Summarizing with qwen2.5:7b ...
  [1/12] 1.1 How to contact us
  ...
  [12/12] (document)
Summarized 12, skipped 0 empty, failed 0 in 56.4s

1  1. Who we are: Covers Brightleaf Coffee Roasters' contact details and information about the data protection officer.
  1.1  How to contact us: Contact details for inquiries about the privacy policy and data handling.
  ...
```

Empty headings are skipped. If one section's LLM call fails, it is left
without a summary and the run continues. If Ollama cannot be reached, the
command exits with code 1 and saves nothing.

### GDPR obligations pack

`packs\gdpr\` holds 19 obligations from GDPR Arts. 12–14 that a privacy
policy can be checked against
([ADR 0004](docs/decisions/0004-regulation-packs.md)). Each one names who has
to do what, when, under which condition, and what evidence usually looks
like:

```yaml
- id: gdpr-13-1-d-legitimate-interests
  ref: "13(1)(d)"
  title: Legitimate interests pursued
  who: controller
  what: Describe the legitimate interests pursued by the controller or by a third party.
  when: At the time when personal data are obtained.
  condition: Any processing is based on legitimate interests (Art. 6(1)(f)).
  evidence: '"We rely on our legitimate interest in ..." naming the actual interest.'
  related: ["14(2)(b)"]
```

`check-pack` links every obligation to the indexed GDPR text (index it first,
see above). It finds the exact paragraph and point, the Art. 4 definitions used
there and the articles it refers to. It exits with code 1 if anything is
missing:

```powershell
regtrace check-pack                                          # packs\gdpr
regtrace check-pack --show gdpr-13-1-d-legitimate-interests  # one obligation in full
```

```text
Definitions: 27 from Article 4
Obligations: 19 (9 conditional)

ID                                   Ref       Node     If  Terms / cross-references
gdpr-13-1-a-controller-identity      13(1)(a)  3.2.1.1      controller, representative
gdpr-13-1-d-legitimate-interests     13(1)(d)  3.2.1.1  yes processing, controller, third party  -> Art. 6(1)(f)
gdpr-13-2-f-automated-decisions      13(2)(f)  3.2.1.2  yes data subject, processing, profiling  -> Art. 22(1), 22(4)
...
OK: all 19 obligations linked
```

Conditional obligations (`If = yes`) only apply in some cases, for example
when a DPO exists or data leave the EEA. They can end in the `depends` status.

### Check a policy

`check` runs every obligation of the pack against an indexed policy and prints
a compliance matrix ([ADR 0006](docs/decisions/0006-evidence-finder.md)). For
each obligation the LLM:

1. reads the policy outline and picks the sections to open,
2. reads them together with the GDPR wording, the Art. 4 definitions it uses
   and the provisions it refers to,
3. returns verbatim quotes, an explanation, a status and a suggested fix,
4. may ask once for more sections if the evidence was not enough.

```powershell
regtrace build-index data\samples\brightleaf-coffee.pdf --summarize
regtrace check data\index\brightleaf-coffee.json
regtrace check data\index\spotify.json --only gdpr-13-2-a-retention
regtrace check data\index\bbc.json --model qwen2.5:14b
```

| Option | Meaning |
|---|---|
| `--pack`, `-p` | Regulation pack folder (default `packs\gdpr`) |
| `--only` | Check only this obligation id (repeatable) |
| `--model`, `-m` | Use another Ollama model for this run |
| `--out`, `-o` | Report JSON (default `data\results\<policy>.<pack>.json`) |

<!-- RESULTS -->

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
- Indexing with `--summarize` makes one LLM call per section (about 1 minute
  for a 2-page policy with `qwen2.5:7b` on a laptop).
- PDFs whose headings are neither bookmarked, in a larger font, nor in the
  EU legal layout are not split into sections.
- Web pages that build their text with JavaScript come out empty, and some
  sites refuse automated downloads (HTTP 403). For those, save the page from
  your browser (Ctrl+S, "Webpage, HTML only") and index the `.html` file.
- Pages that use bold text instead of `<h2>`/`<h3>` headings (for example
  Mozilla's notices) end up with few sections; all text is still kept.
- `check` makes 2–3 LLM calls per obligation (about 40–55 per policy). With
  `qwen2.5:7b` on a laptop that is roughly 10–15 minutes per policy.
- A 7B judge is noisy, especially between `partial` and `compliant`. Quotes
  are not yet verified against the source (Phase 4), and accuracy has not been
  measured yet (Phase 6). Treat results as leads for a human reviewer.
- The `legal` strategy is tuned to the EUR-Lex layout. Other legal texts
  (such as India's DPDP Act) will need their own patterns.

## Changelog

Newest first. Dates are YYYY-MM-DD.

### 2026-11-24
- **Added:** evidence finder and judge (`regtrace.evidence`): tree
  navigation, context expansion with definitions and cross-references,
  five-status judgment with quotes and fixes, the `check` command with a
  compliance matrix and JSON report, and ADR 0006.
- **Added:** ADR 0005 on bottom-up node summaries; Phase 1 is complete.
- **Added:** GDPR obligations pack (`packs/gdpr/`): 19 obligations from
  Arts. 12–14, a loader and linker (`regtrace.regulations`) that attach Art. 4
  definitions and cross-references, the `check-pack` command and ADR 0004.
- **Added:** `scripts/download_policies.py` and `scripts/policies.yaml`: six
  real public privacy policies for evaluation (URLs only, pages stay local).
- **Added:** HTML parser (`regtrace.parsing.html`). `build-index` now accepts
  `.html` files and `http(s)` URLs, plus a `--doc-id` option.
- **Added:** `legal` heading strategy for EU legal texts. The GDPR is now
  parsed into 11 chapters, 99 articles and their paragraphs. `auto` picks it
  when a PDF has no bookmarks but has `Article N` headings.
- **Fixed:** outlines no longer repeat a section number that is already part
  of the heading (`1.1 1.1 How to contact us`).

### 2026-11-20
- **Added:** bottom-up LLM node summaries (`regtrace.tree.summarize`) and the
  `build-index --summarize` option, with progress, timing and failure counts.

### 2026-11-17
- **Added:** section tree model, Ollama LLM client with structured output and
  retries (ADR 0003), PDF parser using bookmarks or font sizes, `llm-check`
  and `build-index` commands, sample policy generator with planted gaps.

### 2026-11-16
- **Added:** project setup: packaging, settings from `.env`, `config`
  command, CI (pytest + ruff), ADRs 0001–0002.

## License

[MIT](LICENSE)
