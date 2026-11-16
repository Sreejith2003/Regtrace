# 0002. Chunkless, tree-based retrieval instead of chunked vector search

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

RegTrace has to decide, for each regulatory obligation (for example "the
controller shall provide the identity and contact details of the controller",
GDPR Art. 13(1)(a)), whether a privacy policy satisfies it, and to cite the
evidence.

The standard RAG approach splits documents into fixed-size chunks, embeds them,
and retrieves the top-k chunks by vector similarity. For compliance analysis
this has specific weaknesses:

- **Structure is lost.** Legal and policy texts are organised hierarchically
  (chapter → article → paragraph → point). Chunk boundaries cut across this
  structure, so a retrieved chunk may lack the heading or condition that gives
  it meaning.
- **Absence is hard to detect.** A gap means the policy *doesn't* say
  something. Top-k similarity always returns *something*, often a
  loosely related passage, which encourages false "compliant" judgments.
- **Context is spread out.** Obligations depend on defined terms (Art. 4) and
  cross-references ("the information referred to in Article 13"). Similarity
  search does not follow these links.
- **Citations are imprecise.** Chunks do not map cleanly onto the section a
  reviewer would cite.

## Decision

Index each document as a **section tree** that follows its own structure
(regulation: chapter → article → paragraph; policy: section → subsection), with
a short LLM-generated summary on each node. Headings come from PDF bookmarks or
font sizes, with an LLM fallback when neither is reliable.

At query time, the LLM **navigates** the policy tree for each obligation: it
reads node summaries, opens promising sections and expands their children,
much like a human analyst skimming a table of contents. Retrieved context is
then **expanded deterministically** with linked definitions and cross-referenced
articles before judgment.

There is no fixed-size chunking and no vector database.

## Consequences

**Benefits**

- Evidence and citations align with real document sections.
- The navigator can conclude "not addressed" after inspecting the relevant
  branches, instead of being handed the nearest chunk.
- Definitions and cross-references are pulled in explicitly, not by luck.
- Fewer moving parts: no embedding model, no vector store.

**Costs and risks**

- **More LLM calls per query.** Navigation is iterative, so latency and cost are
  higher than a single top-k lookup. This is acceptable for a few long
  documents, not for searching thousands.
- **Depends on parsing quality.** Badly structured or scanned PDFs produce poor
  trees. The heading-detection fallback reduces but doesn't remove this risk.
- **Navigation errors.** The model may skip the branch that holds the evidence.
- **Unproven advantage.** The benefits above are hypotheses. A chunked baseline
  using the same LLM and prompts (Phase 5) and a planted-gap evaluation
  (Phase 6) will measure whether tree-based retrieval actually wins on recall,
  false positives and citation correctness.
