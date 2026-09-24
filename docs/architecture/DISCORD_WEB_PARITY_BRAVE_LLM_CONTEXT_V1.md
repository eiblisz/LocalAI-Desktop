# DISCORD WEB PARITY + BRAVE LLM CONTEXT V1

## Purpose

Desktop chat and the authenticated Prometheusz Discord bridge share one action
planning contract. The UI/transport chooses only the current web mode; routing
and grounded web execution remain shared host services.

## Web modes

- `WEB OFF`: local model only. No automatic web fallback.
- `WEB AUTO`: the common planner decides. Fresh/current requests and bounded
  concrete factual-risk relations may use evidence.
- `WEB ON`: keep shared read-only web/evidence routing enabled for external,
  current, and explicit web requests; conversation-local state and recall stay local.

Discord reads the same live Desktop web mode through the bridge. It does not
maintain a second search implementation.

## Brave context strategy

The existing `BRAVE_SEARCH_API_KEY` is reused. No additional secret is stored.

`BRAVE_CONTEXT_MODE=legacy` (default):
Brave Web Search -> LocalAI relevance filtering -> bounded local page fetch ->
normalized evidence.

`BRAVE_CONTEXT_MODE=llm_context`:
Brave LLM Context -> normalized LocalAI evidence. The pre-extracted context skips
LocalAI page fetching when usable grounding is returned.

If LLM Context is unavailable, unauthorized, rate-limited, times out, returns a
malformed response, or contains no usable grounding, the provider chain continues
through the existing Brave Search and existing fallback providers. Provider
errors are retained as diagnostic metadata; the model is never told that failed
evidence succeeded.

Optional tuning:
- `BRAVE_LLM_CONTEXT_MAX_TOKENS` (default 8192; bounded 1024..32768)
- `BRAVE_LLM_CONTEXT_THRESHOLD` (default `strict`)
- existing `BRAVE_SEARCH_COUNTRY` and `BRAVE_SEARCH_LANG`

Official API contract used by this implementation:
`GET https://api.search.brave.com/res/v1/llm/context`
with `X-Subscription-Token`. Grounding uses `grounding.generic[]`
(`url`, `title`, `snippets`) and optional URL-keyed `sources` metadata.

## Normalized evidence

Every successful provider exposes provider-neutral evidence items containing,
when available:

- provider
- query
- retrieved_at
- title
- URL
- relevant text/context
- published/date metadata
- authority
- source metadata

The existing result/source representation remains intact so Desktop source links
and legacy evidence tests continue to work.

## Factual evidence guard

Grounded answers treat the user's premise as a claim to verify. Concrete
person/work, person/event, date/year, version, price, URL, and current-fact
literals must be supported by the user request or authorized evidence. One
bounded repair is allowed; a still-unsupported result fails closed.

This policy is entity-independent. QA names and works are not encoded in the
implementation.

## Timing observability

Set `LOCALAI_TIMING_LOG=1` to emit one sanitized JSON timing record per request.
No prompt body or credential is logged.

Phases include:
- request_received
- routing
- search
- llm_context (when selected)
- page_fetch
- evidence_context_build
- model_inference
- post_processing / factual_guard_repair
- response_send

Search payload diagnostics also include page-fetch count, context characters, and
usable-source count.

## A/B measurement

Legacy and LLM Context should be compared with the same queries and model.
Measure provider/search latency, total latency, local page-fetch count, evidence
character count, usable source count, fallback/errors, and factual regression
results. Do not assume LLM Context is faster or more accurate before live
measurement.
