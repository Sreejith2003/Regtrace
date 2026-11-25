# 0006. Evidence finder: navigate, read, judge, ask for more

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

Phase 3 turns a policy index (ADR 0002, 0005) and a linked pack (ADR 0004)
into one finding per obligation: a status, verbatim quotes, an explanation and
a suggested fix. The model is a 7B local model with an 8k-token context, so a
whole policy plus the regulation text does not fit in one prompt for larger
policies (BBC: 61 sections, IKEA: 71). Small models also tend to decide first
and justify afterwards, and they omit optional JSON fields.

## Decision

For each obligation, `check_obligation` runs up to three structured LLM calls:

1. **Navigate.** The model sees the requirement (title, plain-language
   `what`, evidence hint) and the policy outline, and picks up to 4 section
   ids. The outline uses summaries where they exist and a 120-character text
   snippet where they do not, and drops deeper levels until it fits in 12k
   characters. Ids that do not exist are discarded.
2. **Read.** The chosen sections are read with their subsections, labelled
   `[section 2.1]`, within 3.5k characters per section and 9k in total.
3. **Judge.** The prompt adds context expansion: the official regulation
   wording, the Art. 4 definitions used in it, and the text of up to 3
   cross-referenced provisions (e.g. Art. 6(1)(f) for legitimate interests).
   It also gives the five status rules, including when to answer `depends`
   for a conditional obligation. The reply schema puts the fields in reasoning
   order (`quotes`, `condition_met`, `explanation`, `status`, `fix`), and all
   of them are required, so the model collects evidence before it gives a
   verdict.
4. **Conditions in code, not in the prompt alone.** For a conditional
   obligation the model only says whether the condition holds
   (`yes`/`no`/`unknown`). The checker then decides: `no` → `compliant` (it
   does not apply), and `unknown` with `gap`/`not_addressed` → `depends`. A
   first run without this let the 7B model mark e.g. "language for children"
   as a `gap` for a coffee shop.
5. **Ask for more (once).** The first judgment may list `more_sections` from
   a titles-only outline. If it is not `compliant` and asks for unread
   sections, they are added and the judge runs a final time without that
   option.

Sanity checks after judging: quotes must come from sections that were read
(or their subsections), and `compliant`/`partial` without a quote or a
non-compliant finding without a fix gets a warning. Exact verbatim checking
of quotes is Phase 4. An `LLMError` becomes an error on that finding only,
while an unreachable server stops the run. `regtrace check` prints the matrix
and saves a JSON `Report`.

## Trade-offs

- **Pros:** prompts stay small enough for a local 7B model on long policies.
  Every finding records which sections were read, its quotes and how many
  calls it took, which the evaluation (Phase 6) needs. Context expansion gives
  the judge the legal meaning of terms without sending whole articles.
- **Cons:** 2-3 calls per obligation (about 40-55 per policy, several minutes
  locally). If navigation misses the right section, the judge can only
  recover it through the one extra round. A summary or snippet that hides the
  relevant detail leads to false `not_addressed` results. A 7B judge is noisy
  between `partial` and `compliant`, and Phase 6 measures this against the
  planted gaps rather than tuning prompts by eye.
