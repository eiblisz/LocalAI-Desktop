# Action Planner V2

## Purpose

Action Planner V2 turns one user message into one or more typed, host-validated
action contracts before any side effect starts.

The planner extends the existing LocalAI action runtime. It does not replace the
current chat, web, structured market, memory, artifact, extension, or scheduler
runtimes.

## Contract pipeline

USER REQUEST
-> plan_user_actions()
-> ActionRuntime.plan_many()
-> typed ActionContract sequence
-> host authority validation
-> ordered execution

Each ActionContract contains:

- source-order index;
- bounded prompt for that action unit;
- original ActionPlan;
- execution route;
- web-use flag;
- market-fallback flag;
- required host authorities;
- artifact plans, when applicable.

## Host authorities

V2 currently defines:

- local_model
- memory_write
- external_read
- artifact_create

A contract is rejected before execution when the host does not grant every
required authority.

Examples:

- local chat -> local_model
- explicit memory write -> memory_write
- web/market read -> external_read
- artifact creation -> local_model + artifact_create
- web-grounded artifact -> local_model + artifact_create + external_read

## Multiple action units

Numbered or bulleted multi-task messages are planned independently and preserved
in source order.

Example:

1. current Bitcoin price
2. explain TCP
3. remember a preference
4. create an HTML report

becomes four typed contracts and executes sequentially.

A compound workflow that intentionally belongs together remains one action unit,
for example:

"Find the latest Ollama version and create an HTML report about it."

That contract performs web grounding before bounded artifact creation.

## Desktop execution

Desktop stores the original user message once, then executes the validated
contracts sequentially.

The original multi-task prompt is removed from the model history for each
individual action unit. This prevents later action units from accidentally
re-executing neighboring instructions.

Existing execution paths remain:

- AdaptiveChatWorker
- ChatWebWorker
- MarketDataWorker
- MultiAssetMarketDataWorker
- MemoryWriteWorker

V2 adds ArtifactActionWorker for bounded chat-driven artifact actions.

## Artifact action worker

ArtifactActionWorker:

- accepts only ArtifactPlanItem values;
- optionally obtains grounded web context through the existing read-only web
  runtime;
- asks the selected local model for bounded document/workbook content;
- writes only through the existing artifact_service;
- returns created paths to MainWindow;
- does not run shell commands or arbitrary filesystem actions.

## Discord / Prometheusz

Prometheusz now uses the same ActionRuntime.plan_many() and host validation before
executing its existing remote action flow.

This removes the previous difference where Discord had multi-action planning but
Desktop chose one route for the entire message.

## Failure behavior

Planner authority fails closed before execution.

Runtime worker failures remain bounded to the current action unit. The existing
worker cleanup path then advances to the next queued action contract when one is
pending.

## Acceptance

V2 is accepted when:

- single stable chat behavior remains unchanged;
- structured BTC and stock quote routing remains unchanged;
- explicit memory writes still use MemoryWriteWorker;
- numbered mixed tasks execute in source order;
- a web-grounded artifact remains one compound contract;
- Desktop does not re-inject the full original multi-task prompt into each unit;
- chat-driven PDF/DOCX/XLSX/HTML/summary actions create bounded artifacts;
- missing host authority rejects the action before execution;
- Prometheusz uses the same typed contracts and validation;
- no new patch module is added;
- exact-head GitHub CI passes.
