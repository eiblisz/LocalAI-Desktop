# Request Semantics Profile V1

## Purpose

LocalAI Desktop must decide not only whether a request needs web research, but
what kind of work the user is asking for. A direct factual lookup and an entity
overview have different evidence breadth, latency, and answer-depth needs even
when both use the same web provider.

This profile extends the existing TaskConstraints / ActionRuntime path. It does
not create a second planner or a Discord-specific pipeline.

## Canonical request kinds

- `direct_fact`: one concrete requested fact or relation.
- `entity_overview`: natural overview prompts such as "Mit tudsz X-ről?",
  "Tell me about X", and German equivalents.
- `comparison`: compare two or more subjects.
- `deep_research`: explicit detailed analysis, report, deep dive, or thorough
  research.
- `discovery`: search/recommendation/shopping style requests.
- `explanation`: explain how/why a concept works.
- `general`: ordinary requests not captured by the bounded categories above.

The classifier is based on request shape and explicit user wording. Named QA
entities are never part of the rules.

## Profile contract

Each request receives:

- `response_depth`
- `research_breadth`
- `query_budget`
- `source_budget`
- `page_fetch_budget`

Explicit user constraints override defaults. For example, "Röviden: mit tudsz
X-ről?" remains an entity-overview task but uses concise response depth.

## Execution behavior

Direct factual lookup:
- narrow evidence
- one query
- compact answer
- false-premise correction remains guarded

Entity overview:
- balanced evidence
- direct validated request query (no preliminary model query-generation call)
- more source candidates than a direct lookup
- bounded page fetch
- multi-aspect overview answer instead of automatic 1-3 sentence compaction

Deep research/comparison/discovery:
- broader budgets appropriate to the requested activity
- existing evidence, provider fallback, and grounding safeguards remain active

## Latency

Integer `fetch_pages` values are interpreted as bounded page-fetch budgets.
The legacy boolean `fetch_pages=True` contract remains unchanged.

Small semantic budgets also use a smaller per-page timeout. Search-provider and
legacy fallback behavior remain intact.

## Observability

Request kind, response depth, research breadth, and all semantic budgets are
stored in worker diagnostics and RequestTrace metadata where available.

## Frontend parity

Desktop and Discord both execute the same ChatWebWorker. Request semantics are
derived inside that common worker, so transport choice cannot change task type,
answer-depth contract, or research budget.
