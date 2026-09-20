# Patch Debt Elimination Campaign V1

Status: execution plan for removing all remaining import-time monkey patches.

Base main: `f0359541fe9a6045e3c788fd87e78217bf27a503`

## Goal

End state:

- zero `app/*_patch.py` files;
- zero import-time mutation from `app/__init__.py`;
- explicit controller/pipeline composition only;
- current accepted Desktop behavior preserved;
- patch inventory reports zero active patch modules;
- exact-head Windows CI green.

## Migration order

### Phase A — UI-side MainWindow composition

1. VramController
   - own FREE VRAM button installation;
   - own busy-state guard and Ollama VRAM release action;
   - MainWindow delegates `_release_vram`;
   - `_load_models` explicitly ensures the button.

2. SidebarController
   - own sidebar widget construction;
   - own normal-chat vs schedule-history presentation split;
   - own schedule status rows/history opening;
   - MainWindow delegates `_build_sidebar`, `_load_chat_list`,
     `_refresh_schedule_task_labels`.

3. ImageStudioController
   - own ComfyUI discovery, launch, polling and embedded viewer;
   - own IMAGE tool-button injection;
   - MainWindow delegates `_open_image_studio`,
     `_poll_comfyui_ready`;
   - `_build_tools_panel` explicitly installs IMAGE.

Acceptance gate A:
- no UI patch installer is imported;
- VRAM, sidebar and Image Studio focused tests pass;
- visual/theme contracts remain unchanged.

### Phase B — WebResearchPipeline / EvidencePolicy

4. WebResearchPipeline
   - own shopping provider-query specialization;
   - own shopping-result relevance filtering;
   - own bilingual Hungarian/German query planning policy;
   - own deterministic verified-evidence fallback formatting.

5. EvidencePolicy
   - own authoritative product-price selection;
   - own price-equivalence acceptance for ordinary whole-unit display rounding;
   - canonical evidence functions explicitly call policy helpers.

6. Worker wiring
   - ChatWebWorker owns one explicit WebResearchPipeline instance;
   - search-query planning calls the pipeline directly;
   - evidence fallback receives the ledgers from the current request explicitly;
   - no thread-local mutation bridge.

Acceptance gate B:
- constrained shopping behavior unchanged;
- bilingual expansion behavior unchanged;
- evidence verification/fallback behavior unchanged;
- no web/evidence patch installer is imported.

### Phase C — Patch-free package

7. Delete all eight legacy patch modules.
8. Replace `app/__init__.py` with side-effect-free package metadata only.
9. Update tests that previously asserted monkey-patch wiring to assert explicit
   controller/pipeline composition instead.
10. Update `PATCH_INVENTORY.md` and `patch_inventory.json` to zero active
    patch modules while preserving historical migration record.
11. Strengthen CI contract:
    - fail if any `app/*_patch.py` appears;
    - fail if `app/__init__.py` contains patch installers or runtime mutation;
    - verify explicit controller/pipeline modules exist.

## Non-goals

- no redesign of accepted UI;
- no new scheduler/memory/action-planner architecture;
- no change to extension/browser authority;
- no change to user-facing search semantics;
- no new patch module or compatibility monkey patch.

## Final acceptance

Campaign is complete only when:

1. `app/*_patch.py` count is zero.
2. Importing `app` performs no cross-module mutation.
3. VramController, SidebarController and ImageStudioController are explicit.
4. WebResearchPipeline and EvidencePolicy are explicit.
5. Existing chat/web/market/memory/artifact/scheduler/browser/extension/action
   planner/theme tests remain green.
6. Patch-debt regression tests are green.
7. Exact-head Windows GitHub CI passes.
8. Local smoke acceptance confirms Desktop startup, sidebar, FREE VRAM, Image
   Studio button, web search and constrained shopping still behave as before.


## Acceptance hardening found during local smoke test

The local smoke test exposed two UX-only issues after the architectural migration:

- completed rich-text replies could briefly reset the QTextBrowser viewport to the top;
  the chat renderer now uses a named end anchor plus bounded delayed re-assertion and
  restores focus to the input;
- a generated constrained-shopping answer could be rejected for omitting the verified
  product URL even though the deterministic host fallback was valid; the safety policy
  remains fail-closed, but successful host-verified fallback is now presented as a
  normal verified result instead of exposing the internal rejection reason.

These changes do not weaken evidence verification or alter search authority.
