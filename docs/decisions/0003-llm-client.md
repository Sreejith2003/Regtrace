# 0003. One LLM client interface with structured output

- **Status:** Accepted
- **Date:** 2026-11-17

## Context

Several stages call a language model: node summaries (Phase 1), evidence
navigation and compliance judgment (Phase 3), the chunked baseline (Phase 5)
and the follow-up chat (Phase 7). Each needs machine-readable answers, not
free text. The default model is a small local one (`qwen2.5:7b` via Ollama),
which sometimes returns malformed or incomplete JSON. The evaluation (Phase 6)
also needs to swap models, and the tests must run in CI without a model.

## Decision

All model calls go through `regtrace.llm`:

- **`LLMClient` protocol** with one method,
  `generate_structured(prompt, schema, system=None) -> schema instance`.
  Callers depend on this protocol, never on a provider SDK.
- **`OllamaClient`** implements it with the official `ollama` SDK:
  - passes `schema.model_json_schema()` as Ollama's `format`, so the server
    constrains decoding to the schema;
  - sets `num_ctx` from settings and `temperature=0` for repeatable runs;
  - validates every reply with Pydantic;
  - on a validation failure, sends the error back to the model and retries
    (`max_retries=2` by default), then raises `LLMResponseError`;
  - turns connection failures and Ollama errors into `LLMConnectionError` /
    `LLMError` with an actionable message (`ollama serve`, `ollama pull`).
- A per-client `model` override allows a small model for summaries and a
  larger one for judgment.
- `regtrace llm-check` makes one real call to confirm the setup.

## Trade-offs

- **Pros:** one place for prompts' plumbing, retries and errors; consistent
  validated output; fake clients make higher-level tests fast and offline;
  adding an API model later means adding one class.
- **Cons:** only structured output is supported for now (chat streaming can be
  added when Phase 7 needs it); retries add latency and cost when the model
  struggles; schema-constrained decoding can still produce valid JSON with
  wrong content, so the verification stage (Phase 4) is still required.
