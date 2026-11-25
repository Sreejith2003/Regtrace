# 0007. Quote verification, confidence flags and conditions

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

Each finding (ADR 0006) rests on quotes the judge copied from the policy. A
7B model sometimes paraphrases, joins two sentences, cites the wrong section
id or invents a sentence. A reviewer needs to know which findings are backed
by the text and which are not. On the first real report (Brightleaf) the
quotes were mostly faithful, but the model flattened list markers
(`"\n- "` → `" - "`) and joined list items while skipping the text between
them, so a plain `in` check is too strict and string similarity alone is too
loose.

Conditional obligations (DPO, transfers, children, ...) also need a way out
of `depends`: the policy often cannot tell, but the analyst can.

## Decision

**Verification is a separate layer** (`regtrace.verify`) that runs after
`check_policy`, and also offline on a saved report (`regtrace verify`). It
uses no LLM and changes no status; it only adds evidence and flags.

Every quote gets one grade, from the best match in the policy:

| Grade | Meaning |
|---|---|
| `exact` | same characters, ignoring whitespace and a trailing `[...]` |
| `normalized` | same words in order, ignoring case, punctuation and quote marks |
| `spliced` | every word is there, in order, but from 2+ pieces close together |
| `fuzzy` | at least 75% of the words match (paraphrase) |
| `not_found` | anything less |

The first three count as verified. Matching works on Unicode word tokens with
`difflib.SequenceMatcher` (`autojunk=False`, blocks of 2+ words); pieces more
than `3 × len(quote) + 30` words apart are not stitched together. The cited
section is tried first, then the sections that were read, then the rest of
the tree, deepest first. A quote found elsewhere gets its section id
corrected, and a flag. The matched source span is stored in `source_text` for
clickable citations later (Phase 7).

**Confidence** per finding, from simple rules:

- `low`: an error, any quote `not_found`, or `compliant`/`partial` without a
  verified quote;
- `medium`: `depends`, any flag (fuzzy, spliced, wrong or unread section) or
  any warning (e.g. the condition changed the status);
- `high`: otherwise.

**Conditions.** The checker stores the model's own verdict
(`judged_status`), the condition and `condition_met`, and `resolve_status`
applies the rule in code. `depends` is now only kept for a conditional
obligation with an unknown condition; elsewhere it becomes `partial` (with
quotes) or `not_addressed`. `regtrace check --assume ID=yes|no` answers a
condition: `no` marks the obligation as not applying without any LLM call,
and `yes` overrides the model's guess. The report records the assumptions,
and the CLI lists the remaining open questions.

## Trade-offs

- **Pros:** fast (about 10 ms for a whole report) and deterministic, so it can
  run in CI and in the evaluation (Phase 6) to measure citation correctness.
  Grades say *how* a quote differs, so a spliced quote is not treated like an
  invented one. Keeping statuses unchanged avoids hiding the model's
  behaviour, and the evaluation can score both raw and flagged results.
- **Cons:** a verified quote only shows that the text exists, not that it
  supports the verdict. A `not_addressed` finding has nothing to verify, so a
  missed section still looks `high`. The 75% and spread thresholds are picked
  by hand from one real report. Assumptions are per obligation, so the same
  fact (e.g. data from third parties) must be answered for each obligation
  that depends on it.
