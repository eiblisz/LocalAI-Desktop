# Extension Capability and Permission Authority V1

## Purpose

An installed extension is metadata, not execution authority.

V1 introduces an explicit host-owned decision boundary between extension registry
metadata and runtime execution. A request may use an extension only when all required
conditions are true.

## Decision contract

For an extension execution to be authorized:

1. the extension is installed;
2. the extension is enabled;
3. the extension declares the requested capability;
4. the current host scope grants the permission required by that capability;
5. Desktop chat execution additionally requires the extension to be attached to that
   chat.

If any condition fails, the extension is not executed.

## Host scopes

### Desktop chat

Desktop chat grants read-only external-data permission.

Current structured market capabilities such as:

- crypto_quote
- market_quote
- stock_quote
- forex_quote
- index_quote

may execute only when the matching extension is enabled and attached to the active
chat.

If authority is denied, existing grounded-web fallback behavior remains available.

### Desktop workspace

Workspace navigation grants only workspace-open permission.

TradingView configuration may influence the built-in Browser workspace only when the
installed TradingView preset is enabled and declares market_chart.

### Discord remote

The authenticated Discord bridge grants read-only external-data permission for
structured market lookups. It does not depend on a Desktop chat attachment.

### Background service

Background service startup grants only remote-interface permission.

Prometheusz may start only when the Discord Bot extension is enabled and declares the
remote_chat capability. Credential checks remain separate and are still required.

## Permission classes

V1 defines explicit host permission classes:

- external_read
- external_write
- local_execute
- remote_interface
- workspace_open
- extension_execute

Unknown/custom capabilities map to extension_execute and fail closed unless a future
host scope explicitly grants that permission.

Desktop chat does not grant external_write in V1.

## Security properties

- enabled state alone never grants execution;
- capability declaration alone never grants execution;
- chat attachment alone never grants execution;
- credentials remain outside model prompts;
- write-capable extensions are not implicitly enabled by read-only scopes;
- unknown capabilities fail closed;
- extension execution decisions are deterministic and unit-testable.

## Current integrations

V1 routes these existing paths through ExtensionAuthority:

- Desktop Crypto Market Data
- Desktop Multi-Asset Market Data
- TradingView workspace configuration
- Prometheusz Discord Bot background-service startup
- Discord remote Crypto Market Data
- Discord remote Multi-Asset Market Data

The Image Studio/ComfyUI legacy patch is currently a built-in UI controller path rather
than an ExtensionStore execution path; migrating that patch remains separate patch-debt
work under the documented patch inventory.

## Acceptance

V1 is accepted when:

- enabled + declared capability is still insufficient without host permission;
- Desktop chat structured market execution requires chat attachment;
- disabled extensions are rejected;
- missing capabilities are rejected;
- write capability is rejected from Desktop read-only chat scope;
- Discord remote read-only market execution remains functional;
- Prometheusz startup requires remote_chat authority;
- TradingView config requires workspace-open authority;
- existing web fallback remains intact;
- no new patch module is added;
- exact-head GitHub CI passes.
