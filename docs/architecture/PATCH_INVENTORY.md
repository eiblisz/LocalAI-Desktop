# LocalAI Desktop Patch Inventory

Status: canonical migration ledger for the current import-time patch composition.

Baseline main: `5be80a2fd60f994df78a86f5199a8275ab9d571a`

## Governance rule

**NO NEW PATCH MODULES.**

The existing `app/*_patch.py` files are tolerated only as migration debt. New runtime
capabilities must be implemented through explicit components, controllers, runtimes, or
ordinary module composition.

This document does not authorize additional monkey patches. The machine-readable
inventory is `docs/architecture/patch_inventory.json`, and CI freezes the current patch
module set.

## Why this exists

Importing `app` currently installs multiple patches from `app/__init__.py`. Some wrap
existing functions, some replace canonical `MainWindow` methods, and some add methods.
That creates hidden runtime composition: the implementation visible in a source file is
not always the implementation that executes at runtime.

Sprint 1 makes that composition explicit before any extraction or deletion begins.

## Current install order

| Order | Patch module | Runtime target | Mutation | Migration target |
| ---: | --- | --- | --- | --- |
| 1 | `shopping_search_patch.py` | `app.web_search_tool` | wraps `build_provider_query`, `_filter_relevant_results` | `WebResearchPipeline` |
| 2 | `price_evidence_patch.py` | `app.evidence_verifier` | wraps `build_evidence_ledger` | `WebResearchPipeline / EvidencePolicy` |
| 3 | `answer_verifier_patch.py` | `app.evidence_verifier` | wraps `verify_answer_against_evidence` | `WebResearchPipeline / EvidencePolicy` |
| 4 | `verified_fallback_patch.py` | `app.workers` | wraps `filter_verified_results`, `ChatWebWorker._safe_evidence_failure` | `WebResearchPipeline` |
| 5 | `bilingual_search_patch.py` | `app.workers.ChatWebWorker` | adds bilingual planner, wraps `_generate_search_queries` | `WebResearchPipeline` |
| 6 | `vram_release_patch.py` | `app.main_window.MainWindow` | adds `_release_vram`, wraps `_load_models` | `VramController` |
| 7 | `sidebar_navigation_patch.py` | `app.main_window.MainWindow` | replaces `_build_sidebar`, `_load_chat_list`, `_refresh_schedule_task_labels` | `SidebarController` |
| 8 | `image_studio_patch.py` | `app.main_window.MainWindow` | adds Image Studio methods, wraps `_build_tools_panel` | `ImageStudioController` |

The order above is execution-significant and mirrors the install sequence in
`app/__init__.py`.

## Risk classification

### Highest coupling: MainWindow composition

The following patches mutate `MainWindow` at import time:

- `vram_release_patch.py`
- `sidebar_navigation_patch.py`
- `image_studio_patch.py`

The sidebar patch is the strongest override because it fully replaces three
`MainWindow` methods rather than wrapping them. This is the first UI-side migration
candidate once runtime extraction begins.

### Web/evidence chain

Five patches alter web/evidence behavior:

- `shopping_search_patch.py`
- `price_evidence_patch.py`
- `answer_verifier_patch.py`
- `verified_fallback_patch.py`
- `bilingual_search_patch.py`

These must not be migrated independently without preserving install-order semantics and
the current evidence safety contracts. Their intended destination is an explicit
`WebResearchPipeline` plus bounded evidence policy helpers.

## Migration contract

Each patch removal must satisfy all of the following:

1. Existing user-visible behavior remains unchanged unless a separately approved product
   change says otherwise.
2. The replacement is explicit composition; importing `app` must not be required to
   mutate another module or class.
3. Existing focused tests remain green or are replaced by stronger behavioral tests.
4. Windows GitHub CI is green at the exact candidate head.
5. The corresponding entry is removed from both this document and
   `patch_inventory.json` only in the same change that removes the patch module and its
   install call.
6. No temporary replacement `*_patch.py` is allowed.

## Planned extraction sequence

The broader consolidation plan remains incremental:

1. Freeze and inventory patch composition.
2. Extract `SchedulerRuntime` and `ActionRuntime` from `MainWindow`.
3. Build Memory UI V1.
4. Split scheduler engine/background runner from the Desktop control plane.
5. Introduce explicit extension capability/permission authority.
6. Add browser navigation authority policy.
7. Move to host-authorized Action Planner V2.
8. Consolidate UI theme tokens and harden rendered UI tests.

Patch-specific controller extraction can proceed alongside these steps when dependency
boundaries are clear, but must not create a second hidden composition layer.

## Acceptance for Sprint 1

Sprint 1 is complete when:

- all current patch modules are listed in the machine-readable manifest;
- install order and mutations are documented;
- CI fails if an unapproved new `app/*_patch.py` appears;
- CI verifies that `app/__init__.py` still installs the known patches in the documented
  order;
- no runtime behavior has changed merely to create the inventory.
