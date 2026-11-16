# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

RegTrace makes several non-obvious design bets (tree-based retrieval instead of
chunking, local models, structured obligations). Without a written record, the
reasons behind these choices get lost, and it becomes hard to tell whether a
later change contradicts an earlier decision or deliberately reverses it.

This is also a portfolio project: reviewers should be able to see *why* the
system looks the way it does, not only *what* it does.

## Decision

Record each significant design decision as a short Markdown file in
`docs/decisions/`, named `NNNN-kebab-case-title.md` and numbered sequentially.

Each record contains:

- **Status:** Proposed, Accepted, Superseded by NNNN, or Deprecated
- **Context:** the problem and the forces at play
- **Decision:** what we chose
- **Consequences:** trade-offs, including what gets harder

Records are never rewritten once accepted. A changed decision gets a new record
that supersedes the old one.

## Consequences

- Design rationale lives next to the code and is versioned with it.
- Writing a record takes a few minutes per decision. It is only worth doing for
  choices that affect architecture, evaluation or data handling, not routine
  implementation details.
