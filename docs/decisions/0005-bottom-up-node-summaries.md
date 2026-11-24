# 0005. Bottom-up LLM summaries as the navigation layer

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

The evidence finder (Phase 3) does not search with embeddings
([ADR 0002](0002-chunkless-tree-retrieval.md)). It reads a document's outline
and decides which sections to open, the way an analyst skims a table of
contents. Headings alone are often too vague for that ("Other information",
"Your choices", "a. Information that you give us"). Sending the full text of
every section in each prompt does not fit a small local model's context
(`num_ctx=8192` for `qwen2.5:7b`). Some documents are long: the GDPR index has
about 500 nodes.

## Decision

- Every node gets a short LLM summary of **what it covers**: one or two
  sentences, at most 40 words. The prompt names the kinds of topics to mention
  (data types, purposes, recipients, rights, time limits, contacts). The
  system prompt forbids judging the section or adding anything that is not in
  the text.
- Summaries are built **bottom-up (post-order)**. A leaf is summarized from its
  own text, and a parent from its own text plus its children's titles and
  summaries. Each prompt stays small, a parent's summary describes its whole
  subtree, and the root summary describes the document.
- Section text is cut at `max_chars=6000` (about 1.5k tokens), with a visible
  truncation mark.
- Output is structured (`{"summary": ...}`) through the shared LLM client
  ([ADR 0003](0003-llm-client.md)), with `temperature=0`.
- Failures stay local. Empty nodes are skipped, and a failed call leaves one
  node without a summary (its parent sees the child's title instead) and the
  run continues. Only an unreachable server stops the run, and then nothing is
  saved.
- Summaries are optional (`build-index --summarize`), so parsing can be tested
  and inspected without a model.

## Trade-offs

- **Pros:** the outline becomes a compact, informative map of the document
  that fits in one prompt. A parent's summary reflects all its subsections.
  Summaries are computed once at index time and reused for every obligation.
  Indexing is predictable: one call per non-empty node.
- **Cons:** indexing is slow for large documents (about 1 minute for a 2-page
  policy and well over 30 minutes for the full GDPR on a laptop). A summary
  can leave out the one detail an obligation needs, so the finder must be
  allowed to open sections whose summary looks unrelated, and the evaluation
  measures how often that happens. Errors in a child's summary carry into its
  parent. Truncation hides the end of very long sections. Summaries depend on
  the model, so an index records results for one model only.
