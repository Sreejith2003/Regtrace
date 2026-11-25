# 0008. Chunked RAG baseline

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

The headline result (Phase 6) compares tree navigation (ADR 0002, 0006)
against "normal" RAG. The comparison is only meaningful if everything except
the retrieval step is the same: the model, the judge prompt, the condition
rules, the verification and the amount of evidence the judge sees. CLAUDE.md
rules out a vector database for RegTrace itself, but the baseline is meant to
represent the usual approach, so it uses embeddings.

## Decision

`regtrace.baseline` implements a plain pipeline, selected with
`regtrace check --method chunked`:

1. **Chunk.** The policy tree is flattened into one string (headings and
   text in reading order) and split into chunks of up to 1,000 characters
   with 150 characters of overlap, cut at whitespace. Section structure is
   ignored; each chunk only remembers which nodes it overlaps, for citations.
2. **Embed.** Chunks are embedded once per run with a local Ollama embedding
   model (`LLM_EMBED_MODEL`, default `nomic-embed-text`) through
   `OllamaClient.embed`, so all model calls still go through
   `regtrace.llm`. For nomic models the recommended `search_document:` /
   `search_query:` prefixes are added. Vectors stay in memory and are compared
   with cosine similarity in pure Python. At this size (tens of chunks) a
   vector store or numpy adds nothing.
3. **Retrieve.** The query is the obligation title, its plain-language
   `what` and its evidence hint, which is the same information the tree
   navigator gets. The top 8 chunks (at most about 8,000 characters) are
   used, close to the tree method's 9,000-character evidence budget.
4. **Judge.** The same `judge()` call and prompt, with the chunks labelled
   `[section c3]`, but without the "ask for more sections" round, because
   there is no outline to ask from. That is one LLM call per obligation
   instead of 2–3.
5. **Same post-processing.** `finish_finding` (conditions, `depends`, fixes,
   warnings) is shared with the tree checker, and quote verification
   (ADR 0007) runs on both reports. Quotes that cite a chunk id are mapped back
   to the deepest policy section containing them, so citation correctness is
   scored in the same terms for both methods.

Reports record `method: chunked` and are saved as
`<policy>.<pack>.chunked.json` next to the tree reports.

## Trade-offs

- **Pros:** a fair, small baseline. It uses the same judge, the same rules,
  the same verification and a similar evidence budget, so differences come
  from retrieval. It is cheap: one generation call per obligation plus one
  embedding call. It adds no new dependency beyond one Ollama model.
- **Cons:** the synthetic sample policies are short (Stridewell is about
  2,500 characters, so 3 chunks), so top-8 retrieval returns the whole
  document. There the baseline is really "whole document in context", which
  is a strong opponent, and retrieval only matters on long real policies
  (BBC, Spotify, IKEA). Phase 6 must report results for short and long
  policies separately. Chunk size, overlap and k are common defaults, not
  tuned values. A tuned baseline could do better, and the evaluation
  should say so.
