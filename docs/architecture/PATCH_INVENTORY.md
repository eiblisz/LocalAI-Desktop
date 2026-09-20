# LocalAI Desktop Patch Inventory

Status: **migration complete — zero active import-time patches.**

Migration campaign base: `f0359541fe9a6045e3c788fd87e78217bf27a503`

## Governance rule

**NO PATCH MODULES.**

The previous import-time monkey-patch layer has been removed. New runtime capabilities
must use explicit components, controllers, runtimes, policies, or ordinary module
composition. A new `app/*_patch.py` file is a CI failure.

## Current active inventory

Active patch modules: **0**

Import-time patch installers in `app/__init__.py`: **0**

`app/__init__.py` is intentionally side-effect free.

## Completed migrations

| Former patch | Canonical replacement | Preserved responsibility |
| --- | --- | --- |
| `vram_release_patch.py` | `VramController` | FREE VRAM control, busy guard, Ollama unload |
| `sidebar_navigation_patch.py` | `SidebarController` | sidebar/navigation, schedule-history rows, normal-chat filtering |
| `image_studio_patch.py` | `ImageStudioController` | ComfyUI launch/readiness/embed and IMAGE tool |
| `shopping_search_patch.py` | `WebResearchPipeline` | constrained shopping query specialization and result filtering |
| `bilingual_search_patch.py` | `WebResearchPipeline` | Hungarian/German shopping query planning |
| `verified_fallback_patch.py` | `WebResearchPipeline` | deterministic VERIFIED-evidence fallback |
| `price_evidence_patch.py` | `EvidencePolicy` | authoritative product-price evidence selection |
| `answer_verifier_patch.py` | `EvidencePolicy` | verified price/display-rounding equivalence |

## Explicit composition

### MainWindow

`MainWindow` owns:

- `VramController`
- `SidebarController`
- `ImageStudioController`

The canonical MainWindow methods delegate explicitly to those controllers. No class
methods are replaced at import time.

### Web research

`ChatWebWorker` owns a `WebResearchPipeline`. Bilingual query expansion and
deterministic evidence fallback are explicit worker/pipeline calls.

`web_search_tool` explicitly delegates constrained-shopping specialization to
`WebResearchPipeline`.

`evidence_verifier` explicitly delegates price evidence and answer-price equivalence
to `EvidencePolicy`.

No thread-local monkey-patch bridge is used for VERIFIED fallback data; the current
worker carries its current evidence ledgers explicitly.

## Historical install order

Before migration the order was:

1. shopping search
2. price evidence
3. answer verifier
4. verified fallback
5. bilingual search
6. VRAM release
7. sidebar navigation
8. Image Studio

The canonical replacements preserve the resulting accepted behavior without depending
on import order.

## CI contract

The repository must fail CI if:

- any `app/*_patch.py` file exists;
- `app/__init__.py` imports or executes a patch installer;
- the machine-readable inventory reports an active patch;
- required canonical replacement modules are missing;
- explicit controller/pipeline wiring disappears.

## Completion acceptance

Patch-debt elimination is complete when:

- patch-module count is zero;
- import-time mutation count is zero;
- all prior focused behavior tests are preserved or strengthened;
- full Windows GitHub CI passes at the exact candidate head;
- local smoke testing confirms the accepted Desktop UI and web behavior.
