# 0004. Regulation packs as hand-written YAML linked to the indexed text

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

The evidence finder (Phase 3) needs a list of concrete things to look for in a
policy. Raw article text is a poor unit for that. One GDPR paragraph such as
Art. 13(1) bundles six separate requirements, some of which only apply under
conditions ("where applicable", "where the processing is based on point (f) of
Article 6(1)"). The judge also needs the defined meaning of terms like
"controller" or "consent", and the articles a provision points to. The
evaluation (Phase 6) needs stable ids to score results against planted gaps,
and later regulations (DPDP Act, EU AI Act) should plug in without code
changes.

## Decision

- A **pack** is a folder: `pack.yaml` (id, name, regulation, path to the
  regulation index, which article holds the definitions) and
  `obligations.yaml`.
- Each **obligation** is written by hand: `id`, `ref` (`13(1)(a)`), `title`,
  `who`, `what`, `when`, an optional `condition`, an `evidence` hint and
  `related` parallel provisions (Art. 13 ↔ Art. 14). Pydantic validates the
  file. Ids are unique and never reused, so evaluation results stay comparable.
- Obligations are **linked, not copied**. `link_pack` finds the article,
  paragraph and point in the regulation's section tree and takes the official
  wording from there. It also attaches the Art. 4 definitions that occur in it
  and extracts cross-references (`point (f) of Article 6(1)`,
  `Articles 15 to 22`, `Article 22(1) and (4)`), skipping references to other
  acts.
- An obligation with a `condition` can end in the `depends` status when the
  policy does not show whether the condition holds.
- `regtrace check-pack` fails if any reference, point or definition cannot be
  found, so a broken pack is caught in CI and by hand before any LLM run.

## Trade-offs

- **Pros:** obligations are small, reviewable and versioned with the code. The
  regulation's own wording stays the source of truth. Definitions and
  cross-references come for free from the tree built in Phase 1. A new
  regulation is mostly a new YAML file.
- **Cons:** writing obligations takes legal reading, and the plain-language
  `what` can drift from the text (mitigated by showing both side by side in
  `check-pack --show`). The definition and cross-reference patterns are tuned
  to EU drafting style. Term matching is literal, so "controllers" matches but
  "the company" does not; mapping a policy's own wording to defined terms is
  left to the LLM in Phase 3.
