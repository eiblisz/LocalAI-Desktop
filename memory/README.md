# LocalAI Desktop Memory V1

## Core principle

The LocalAI Desktop owns the persistent memory.
The language model is a replaceable component.

Memory must remain usable when Qwen, Devstral, or any future model is replaced.


## Runtime location

The versioned `memory/` directory in the repository contains architecture documentation and schemas only.

Private live memory is stored under the clone-independent user runtime root. On Windows the default canonical database is:

```text
%LOCALAPPDATA%\LocalAI-Desktop\memory\canonical\memory.sqlite3
```

The root may be overridden with `LOCALAI_DESKTOP_DATA_DIR`. Legacy repo-local private memory is copied once into the stable runtime root without deleting the original source.

## Storage roles

canonical/
  Authoritative persistent memory. Source of truth.

vectors/
  Rebuildable embeddings/vector indexes.
  Never authoritative.

documents/
  Optional source documents used by the memory system.

archive/
  Superseded or retired memory records.

exports/
  Portable memory exports.

backups/
  Local memory backups.

schemas/
  Versioned schemas defining the portable memory format.

## Memory classes

explicit
  The user explicitly requested persistence, for example:
  "Remember that..."
  This has the highest user-memory authority.

candidate
  Information inferred to be potentially useful long-term.
  It must not silently override explicit user memory.

temporary
  Session or short-lived context.
  It is not durable canonical memory by default.

## Memory rules

1. Explicit user memory is durable.
2. The model itself is not the memory store.
3. Canonical memory must be model-independent.
4. Vector embeddings are derived and rebuildable.
5. Personal runtime memory must not be committed to Git.
6. Every durable record has a stable ID and provenance.
7. Existing facts are updated/versioned rather than duplicated blindly.
8. Contradictory inferred memories cannot override explicit user statements.
9. Memory must support correction, superseding, and deletion.
10. The canonical format must remain exportable without a specific AI model.

## Example

User:

"Remember that my preferred shell is PowerShell."

Canonical semantic record:

- subject: user
- predicate: preferred_shell
- object: PowerShell
- memory_class: explicit
- source: user
- status: active

A future model receives the same canonical fact without retraining.
